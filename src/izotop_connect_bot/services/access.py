from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from izotop_connect_bot.config import Settings
from izotop_connect_bot.db import session_scope
from izotop_connect_bot.repositories import (
    AdminUserRow,
    DashboardStats,
    DeviceAddonSubscriptionRepository,
    ManualImportRepository,
    PromoCodeRedemptionRepository,
    PromoCodeRepository,
    SubscriptionRepository,
    UserRepository,
    VpnAccountRepository,
    WebhookEventRepository,
    WebhookEventRow,
    WhiteTopUpOrderRepository,
    WhiteTrafficCycleRepository,
    WhiteVpnAccountRepository,
    ensure_utc,
    normalize_telegram_username,
    subscription_is_active,
    user_view_model,
)
from izotop_connect_bot.services.remnawave import RemnawaveService
from izotop_connect_bot.services.tribute import TributeEvent, TributeService


@dataclass(slots=True)
class AccessBundle:
    user: Any
    subscription: Any
    vpn_account: Any
    is_active: bool
    expires_at: datetime | None
    base_device_limit: int | None = None
    device_addon_bonus: int = 0
    effective_device_limit: int | None = None


@dataclass(slots=True)
class WhiteAccessState:
    vpn_account: Any
    cycle: Any
    is_enabled: bool
    is_unlimited: bool
    current_used_bytes: int
    current_free_remaining_bytes: int
    purchased_remaining_bytes: int
    traffic_limit_bytes: int | None


@dataclass(slots=True)
class WebhookProcessResult:
    event: TributeEvent
    is_duplicate: bool = False
    notification_telegram_user_id: int | None = None
    notification_text: str | None = None


def normalize_promo_code(code: str) -> str:
    return code.replace("\r\n", "\n").strip()


PROMO_DEVICE_LIMIT = 1
BYTES_PER_GB = 1024**3
DEVICE_ADDON_SUBSCRIPTION_BONUSES = {
    "+3 устройства на Izotop Connect": 3,
    "+6 устройств на Izotop Connect": 6,
    "+9 устройств на Izotop Connect": 9,
}


def _normalize_admin_lookup(value: str) -> str:
    return value.strip()


class AccessService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        remnawave: RemnawaveService,
        tribute: TributeService,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.remnawave = remnawave
        self.tribute = tribute
        self.users = UserRepository()
        self.subscriptions = SubscriptionRepository()
        self.vpn_accounts = VpnAccountRepository()
        self.white_vpn_accounts = WhiteVpnAccountRepository()
        self.white_traffic_cycles = WhiteTrafficCycleRepository()
        self.white_topup_orders = WhiteTopUpOrderRepository()
        self.device_addon_subscriptions = DeviceAddonSubscriptionRepository()
        self.webhook_events = WebhookEventRepository()
        self.manual_imports = ManualImportRepository()
        self.promo_codes = PromoCodeRepository()
        self.promo_redemptions = PromoCodeRedemptionRepository()

    @property
    def white_monthly_free_bytes(self) -> int:
        return max(0, self.settings.white_monthly_free_gb) * BYTES_PER_GB

    def _white_feature_enabled(self) -> bool:
        return bool(self.settings.remnawave_white_internal_squad_uuid)

    def _resolve_device_addon_bonus(self, subscription_name: str | None) -> int | None:
        if not subscription_name:
            return None
        return DEVICE_ADDON_SUBSCRIPTION_BONUSES.get(subscription_name.strip())

    async def _calculate_device_limits(
        self,
        session: AsyncSession,
        *,
        user: Any | None,
    ) -> tuple[int | None, int, int | None]:
        if user is None:
            return None, 0, None
        base_device_limit = max(1, int(user.device_limit or self.settings.remnawave_default_device_limit))
        device_addon_bonus = await self.device_addon_subscriptions.sum_active_bonus(
            session,
            user.telegram_user_id,
        )
        return base_device_limit, device_addon_bonus, base_device_limit + device_addon_bonus

    async def _build_access_bundle(
        self,
        session: AsyncSession,
        *,
        user: Any | None,
        subscription: Any,
        vpn_account: Any,
    ) -> AccessBundle:
        base_device_limit, device_addon_bonus, effective_device_limit = await self._calculate_device_limits(
            session,
            user=user,
        )
        model = user_view_model(user, subscription, vpn_account)
        return AccessBundle(
            **model,
            base_device_limit=base_device_limit,
            device_addon_bonus=device_addon_bonus,
            effective_device_limit=effective_device_limit,
        )

    def _is_white_unlimited(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self.settings.white_unlimited_user_ids

    def _resolve_white_topup_granted_bytes(
        self,
        *,
        amount_minor: int | None,
        currency: str | None,
    ) -> int | None:
        if amount_minor is None:
            return None
        currency_value = (currency or "rub").strip().casefold()
        if currency_value not in {"rub", "rur"}:
            return None
        if self.settings.white_price_per_gb_rub <= 0:
            return None
        granted_bytes = amount_minor * BYTES_PER_GB // (self.settings.white_price_per_gb_rub * 100)
        return granted_bytes if granted_bytes > 0 else None

    def _format_white_topup_gigabytes(self, granted_bytes: int) -> str:
        gigabytes = Decimal(granted_bytes) / Decimal(BYTES_PER_GB)
        normalized = gigabytes.normalize()
        text = format(normalized, "f").rstrip("0").rstrip(".")
        return text or "0"

    def _format_white_remaining_text(self, remaining_bytes: int, *, is_unlimited: bool) -> str:
        if is_unlimited:
            return "безлимитно"
        gigabytes = Decimal(max(0, remaining_bytes)) / Decimal(BYTES_PER_GB)
        return f"~{gigabytes:.2f}".replace(".", ",") + " гигабайт"

    def _build_white_topup_notification_text(
        self,
        *,
        amount_minor: int,
        granted_bytes: int,
        white_access: WhiteAccessState,
    ) -> str:
        amount_rub = Decimal(amount_minor) / Decimal(100)
        amount_text = format(amount_rub.normalize(), "f").rstrip("0").rstrip(".") or "0"
        granted_gb = self._format_white_topup_gigabytes(granted_bytes)
        total_remaining_bytes = (
            white_access.current_free_remaining_bytes + white_access.purchased_remaining_bytes
        )
        total_remaining = self._format_white_remaining_text(
            total_remaining_bytes,
            is_unlimited=white_access.is_unlimited,
        )
        return (
            f"Платеж получен: <b>{amount_text} ₽</b>.\n\n"
            f"Начислено <b>{granted_gb} GB</b> белого трафика.\n"
            f"Сейчас доступно: <b>{total_remaining}</b>"
        )

    def _build_device_addon_notification_text(
        self,
        *,
        added_devices: int,
        effective_device_limit: int,
        base_subscription_active: bool,
    ) -> str:
        if base_subscription_active:
            return (
                "Платеж получен.\n\n"
                f"Добавлено <b>+{added_devices}</b> устройства.\n"
                f"Сейчас доступно: <b>{effective_device_limit}</b> устройств."
            )
        return (
            "Платеж получен.\n\n"
            f"Добавлено <b>+{added_devices}</b> устройства.\n"
            "Основная подписка сейчас неактивна, поэтому бонус сохранён и автоматически применится после её активации."
        )

    @staticmethod
    def _white_donation_order_uuid(event: TributeEvent) -> str:
        digest = hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()
        return f"donation:{digest[:48]}"

    async def _sync_regular_account(
        self,
        session: AsyncSession,
        *,
        user: Any,
        expires_at: datetime | None,
    ) -> Any:
        _, _, effective_device_limit = await self._calculate_device_limits(session, user=user)
        remote = await self.remnawave.sync_access(
            telegram_user_id=user.telegram_user_id,
            telegram_username=user.telegram_username,
            first_name=user.first_name,
            expires_at=expires_at,
            device_limit=effective_device_limit or self.settings.remnawave_default_device_limit,
        )
        vpn_account = await self.vpn_accounts.get_account(session, user.telegram_user_id)
        if remote is not None and getattr(remote, "subscription_url", None):
            vpn_account = await self.vpn_accounts.upsert_account(
                session,
                telegram_user_id=user.telegram_user_id,
                remnawave_user_uuid=str(remote.uuid),
                remnawave_username=remote.username,
                subscription_url=remote.subscription_url,
            )
        return vpn_account

    async def _ensure_white_cycle(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        expires_at: datetime,
        current_used_bytes: int,
    ) -> Any | None:
        now = datetime.now(UTC)
        latest_cycle = await self.white_traffic_cycles.get_latest_cycle(session, telegram_user_id)
        if latest_cycle is None:
            return await self.white_traffic_cycles.create_cycle(
                session,
                telegram_user_id=telegram_user_id,
                started_at=now,
                expires_at=expires_at,
                free_bytes=self.white_monthly_free_bytes,
                start_used_bytes=current_used_bytes,
            )

        latest_expires_at = ensure_utc(latest_cycle.expires_at)
        if latest_expires_at is None:
            return latest_cycle

        if expires_at > latest_expires_at:
            next_cycle_start = latest_expires_at if latest_expires_at > now else now
            start_used_bytes = current_used_bytes if next_cycle_start <= now else None
            new_cycle = await self.white_traffic_cycles.create_cycle(
                session,
                telegram_user_id=telegram_user_id,
                started_at=next_cycle_start,
                expires_at=expires_at,
                free_bytes=self.white_monthly_free_bytes,
                start_used_bytes=start_used_bytes,
            )
            if start_used_bytes is not None and latest_cycle.end_used_bytes is None:
                latest_cycle.end_used_bytes = current_used_bytes
            return new_cycle

        active_cycle = await self.white_traffic_cycles.get_active_cycle(session, telegram_user_id, at=now)
        if active_cycle is not None and active_cycle.start_used_bytes is None:
            active_cycle.start_used_bytes = current_used_bytes
            cycles = await self.white_traffic_cycles.list_cycles(session, telegram_user_id)
            for cycle in reversed(cycles):
                if cycle.id == active_cycle.id:
                    continue
                cycle_expires_at = ensure_utc(cycle.expires_at)
                if cycle_expires_at and cycle_expires_at <= ensure_utc(active_cycle.started_at) and cycle.end_used_bytes is None:
                    cycle.end_used_bytes = current_used_bytes
                    break
        return active_cycle or latest_cycle

    async def _calculate_white_purchased_remaining_bytes(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        current_used_bytes: int,
        active_cycle: Any | None,
    ) -> int:
        total_paid_bytes = await self.white_topup_orders.sum_paid_bytes(session, telegram_user_id)
        cycles = await self.white_traffic_cycles.list_cycles(session, telegram_user_id)
        consumed_paid_bytes = 0
        active_cycle_id = getattr(active_cycle, "id", None)
        for cycle in cycles:
            start_used_bytes = cycle.start_used_bytes
            if start_used_bytes is None:
                continue
            end_used_bytes = cycle.end_used_bytes
            if cycle.id == active_cycle_id:
                end_used_bytes = current_used_bytes
            if end_used_bytes is None or end_used_bytes < start_used_bytes:
                continue
            cycle_used_bytes = end_used_bytes - start_used_bytes
            consumed_paid_bytes += max(0, cycle_used_bytes - cycle.free_bytes)
        return max(0, total_paid_bytes - consumed_paid_bytes)

    async def _sync_white_state(
        self,
        session: AsyncSession,
        *,
        user: Any,
        expires_at: datetime | None,
    ) -> WhiteAccessState:
        existing_remote = await self.remnawave.get_white_user(user.telegram_user_id)
        existing_used_bytes = self.remnawave.extract_used_traffic_bytes(existing_remote)
        _, _, effective_device_limit = await self._calculate_device_limits(session, user=user)

        if not self._white_feature_enabled():
            return WhiteAccessState(
                vpn_account=None,
                cycle=None,
                is_enabled=False,
                is_unlimited=False,
                current_used_bytes=existing_used_bytes,
                current_free_remaining_bytes=0,
                purchased_remaining_bytes=0,
                traffic_limit_bytes=None,
            )

        if expires_at is None or expires_at <= datetime.now(UTC):
            latest_cycle = await self.white_traffic_cycles.get_latest_cycle(session, user.telegram_user_id)
            if (
                latest_cycle is not None
                and latest_cycle.start_used_bytes is not None
                and latest_cycle.end_used_bytes is None
            ):
                latest_cycle.end_used_bytes = existing_used_bytes
            purchased_remaining_bytes = await self._calculate_white_purchased_remaining_bytes(
                session,
                telegram_user_id=user.telegram_user_id,
                current_used_bytes=existing_used_bytes,
                active_cycle=None,
            )
            remote = await self.remnawave.sync_white_access(
                telegram_user_id=user.telegram_user_id,
                telegram_username=user.telegram_username,
                first_name=user.first_name,
                expires_at=None,
                device_limit=effective_device_limit or self.settings.remnawave_default_device_limit,
                traffic_limit_bytes=None,
            )
            if remote is not None:
                await self.white_vpn_accounts.delete_account(session, user.telegram_user_id)
            return WhiteAccessState(
                vpn_account=None,
                cycle=None,
                is_enabled=False,
                is_unlimited=self._is_white_unlimited(user.telegram_user_id),
                current_used_bytes=existing_used_bytes,
                current_free_remaining_bytes=0,
                purchased_remaining_bytes=purchased_remaining_bytes,
                traffic_limit_bytes=None,
            )

        if self._is_white_unlimited(user.telegram_user_id):
            remote = await self.remnawave.sync_white_access(
                telegram_user_id=user.telegram_user_id,
                telegram_username=user.telegram_username,
                first_name=user.first_name,
                expires_at=expires_at,
                device_limit=effective_device_limit or self.settings.remnawave_default_device_limit,
                traffic_limit_bytes=None,
            )
            vpn_account = await self.white_vpn_accounts.get_account(session, user.telegram_user_id)
            if remote is not None and getattr(remote, "subscription_url", None):
                vpn_account = await self.white_vpn_accounts.upsert_account(
                    session,
                    telegram_user_id=user.telegram_user_id,
                    remnawave_user_uuid=str(remote.uuid),
                    remnawave_username=remote.username,
                    subscription_url=remote.subscription_url,
                )
            return WhiteAccessState(
                vpn_account=vpn_account,
                cycle=None,
                is_enabled=True,
                is_unlimited=True,
                current_used_bytes=self.remnawave.extract_used_traffic_bytes(remote),
                current_free_remaining_bytes=0,
                purchased_remaining_bytes=0,
                traffic_limit_bytes=None,
            )

        active_cycle = await self._ensure_white_cycle(
            session,
            telegram_user_id=user.telegram_user_id,
            expires_at=expires_at,
            current_used_bytes=existing_used_bytes,
        )
        cycle_start_used_bytes = (
            active_cycle.start_used_bytes if active_cycle is not None and active_cycle.start_used_bytes is not None else existing_used_bytes
        )
        cycle_used_bytes = max(0, existing_used_bytes - cycle_start_used_bytes)
        current_free_remaining_bytes = max(0, (active_cycle.free_bytes if active_cycle is not None else 0) - cycle_used_bytes)
        purchased_remaining_bytes = await self._calculate_white_purchased_remaining_bytes(
            session,
            telegram_user_id=user.telegram_user_id,
            current_used_bytes=existing_used_bytes,
            active_cycle=active_cycle,
        )
        traffic_limit_bytes = existing_used_bytes + current_free_remaining_bytes + purchased_remaining_bytes
        remote = await self.remnawave.sync_white_access(
            telegram_user_id=user.telegram_user_id,
            telegram_username=user.telegram_username,
            first_name=user.first_name,
            expires_at=expires_at,
            device_limit=effective_device_limit or self.settings.remnawave_default_device_limit,
            traffic_limit_bytes=traffic_limit_bytes,
        )
        current_used_bytes = self.remnawave.extract_used_traffic_bytes(remote)
        if active_cycle is not None and active_cycle.start_used_bytes is None:
            active_cycle.start_used_bytes = current_used_bytes
        if active_cycle is not None and active_cycle.start_used_bytes is not None:
            cycle_used_bytes = max(0, current_used_bytes - active_cycle.start_used_bytes)
            current_free_remaining_bytes = max(0, active_cycle.free_bytes - cycle_used_bytes)
            purchased_remaining_bytes = await self._calculate_white_purchased_remaining_bytes(
                session,
                telegram_user_id=user.telegram_user_id,
                current_used_bytes=current_used_bytes,
                active_cycle=active_cycle,
            )
            traffic_limit_bytes = current_used_bytes + current_free_remaining_bytes + purchased_remaining_bytes
            if traffic_limit_bytes != getattr(remote, "traffic_limit_bytes", traffic_limit_bytes):
                remote = await self.remnawave.sync_white_access(
                    telegram_user_id=user.telegram_user_id,
                    telegram_username=user.telegram_username,
                    first_name=user.first_name,
                    expires_at=expires_at,
                    device_limit=effective_device_limit or self.settings.remnawave_default_device_limit,
                    traffic_limit_bytes=traffic_limit_bytes,
                )
                current_used_bytes = self.remnawave.extract_used_traffic_bytes(remote)

        vpn_account = await self.white_vpn_accounts.get_account(session, user.telegram_user_id)
        if remote is not None and getattr(remote, "subscription_url", None):
            vpn_account = await self.white_vpn_accounts.upsert_account(
                session,
                telegram_user_id=user.telegram_user_id,
                remnawave_user_uuid=str(remote.uuid),
                remnawave_username=remote.username,
                subscription_url=remote.subscription_url,
            )
        return WhiteAccessState(
            vpn_account=vpn_account,
            cycle=active_cycle,
            is_enabled=True,
            is_unlimited=False,
            current_used_bytes=current_used_bytes,
            current_free_remaining_bytes=current_free_remaining_bytes,
            purchased_remaining_bytes=purchased_remaining_bytes,
            traffic_limit_bytes=traffic_limit_bytes,
        )

    async def _grant_active_subscription(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        language_code: str | None,
        expires_at: datetime,
        device_limit: int | None,
        source: str,
        imported_by_admin: int | None = None,
        note: str | None = None,
    ) -> AccessBundle:
        user = await self.users.upsert_user(
            session,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            language_code=language_code,
            is_admin=telegram_user_id in self.settings.bot_admin_ids,
            device_limit=device_limit or self.settings.remnawave_default_device_limit,
            preserve_missing_fields=True,
        )
        await self.subscriptions.upsert_subscription(
            session,
            telegram_user_id=telegram_user_id,
            tribute_subscription_id=None,
            period_id=None,
            channel_id=None,
            status="ACTIVE",
            expires_at=ensure_utc(expires_at),
            cancelled=False,
            source=source,
        )
        if imported_by_admin is not None:
            await self.manual_imports.add(
                session,
                telegram_user_id=telegram_user_id,
                expires_at=ensure_utc(expires_at),
                note=note,
                imported_by_admin=imported_by_admin,
            )
        vpn_account = await self._sync_regular_account(
            session,
            user=user,
            expires_at=ensure_utc(expires_at),
        )
        await self._sync_white_state(
            session,
            user=user,
            expires_at=ensure_utc(expires_at),
        )
        subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
        return await self._build_access_bundle(
            session,
            user=user,
            subscription=subscription,
            vpn_account=vpn_account,
        )

    async def register_telegram_user(self, tg_user: TgUser) -> Any:
        async with session_scope(self.session_factory) as session:
            return await self.users.upsert_user(
                session,
                telegram_user_id=tg_user.id,
                telegram_username=tg_user.username,
                first_name=tg_user.first_name,
                language_code=tg_user.language_code,
                is_admin=tg_user.id in self.settings.bot_admin_ids,
                device_limit=None,
            )

    async def get_access_bundle(self, telegram_user_id: int) -> AccessBundle:
        async with session_scope(self.session_factory) as session:
            user = await self.users.get_user(session, telegram_user_id)
            subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, telegram_user_id)
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def get_white_access_state(self, telegram_user_id: int) -> WhiteAccessState:
        async with session_scope(self.session_factory) as session:
            user = await self.users.get_user(session, telegram_user_id)
            subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            if user is None:
                return WhiteAccessState(
                    vpn_account=None,
                    cycle=None,
                    is_enabled=False,
                    is_unlimited=False,
                    current_used_bytes=0,
                    current_free_remaining_bytes=0,
                    purchased_remaining_bytes=0,
                    traffic_limit_bytes=None,
                )
            expires_at = ensure_utc(subscription.expires_at) if subscription and subscription_is_active(subscription) else None
            return await self._sync_white_state(
                session,
                user=user,
                expires_at=expires_at,
            )

    async def ensure_vpn_access(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
    ) -> Any:
        async with session_scope(self.session_factory) as session:
            user = await self.users.get_user(session, telegram_user_id)
            subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            if user is None:
                raise ValueError("User not found")
            if not subscription_is_active(subscription):
                raise PermissionError("Subscription inactive")

            expires_at = ensure_utc(subscription.expires_at)
            if expires_at is None:
                raise PermissionError("Subscription inactive")
            remote = await self.remnawave.sync_access(
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                first_name=first_name,
                expires_at=expires_at,
                device_limit=user.device_limit,
            )
            vpn_account = await self.vpn_accounts.upsert_account(
                session,
                telegram_user_id=telegram_user_id,
                remnawave_user_uuid=str(remote.uuid),
                remnawave_username=remote.username,
                subscription_url=remote.subscription_url,
            )
            await self._sync_white_state(
                session,
                user=user,
                expires_at=expires_at,
            )
            return vpn_account

    async def refresh_remote_state(self, telegram_user_id: int) -> AccessBundle:
        async with session_scope(self.session_factory) as session:
            user = await self.users.get_user(session, telegram_user_id)
            subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, telegram_user_id)
            expires_at = ensure_utc(subscription.expires_at) if subscription else None
            if user and subscription and expires_at:
                vpn_account = await self._sync_regular_account(
                    session,
                    user=user,
                    expires_at=expires_at if subscription_is_active(subscription) else None,
                )
                await self._sync_white_state(
                    session,
                    user=user,
                    expires_at=expires_at if subscription_is_active(subscription) else None,
                )
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def process_tribute_webhook(self, headers: dict[str, str], body: bytes) -> WebhookProcessResult:
        if not self.tribute.verify_signature(headers, body):
            raise PermissionError("Invalid Tribute signature")

        payload = json.loads(body.decode("utf-8"))
        event = self.tribute.parse_event(payload)
        result = WebhookProcessResult(event=event)

        async with session_scope(self.session_factory) as session:
            if await self.webhook_events.exists(session, event.event_key):
                result.is_duplicate = True
                return result

            if event.is_subscription_event and event.telegram_user_id is not None:
                user = await self.users.upsert_user(
                    session,
                    telegram_user_id=event.telegram_user_id,
                    telegram_username=event.telegram_username,
                    first_name=None,
                    language_code=None,
                    is_admin=event.telegram_user_id in self.settings.bot_admin_ids,
                    device_limit=None,
                    preserve_missing_fields=True,
                )
                expires_at = ensure_utc(event.expires_at)
                status = "ACTIVE" if expires_at and expires_at > datetime.now(UTC) else "INACTIVE"
                device_addon_bonus = self._resolve_device_addon_bonus(event.subscription_name)
                if device_addon_bonus is not None:
                    await self.device_addon_subscriptions.upsert_subscription(
                        session,
                        telegram_user_id=user.telegram_user_id,
                        tribute_subscription_id=event.tribute_subscription_id,
                        subscription_name=event.subscription_name or f"+{device_addon_bonus} устройства",
                        period_id=event.period_id,
                        channel_id=event.channel_id,
                        bonus_devices=device_addon_bonus,
                        status=status,
                        expires_at=expires_at,
                        cancelled=event.cancelled,
                        source="tribute",
                    )
                    subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
                    subscription_expires_at = (
                        ensure_utc(subscription.expires_at)
                        if subscription and subscription_is_active(subscription)
                        else None
                    )
                    if subscription_expires_at is not None:
                        await self._sync_regular_account(
                            session,
                            user=user,
                            expires_at=subscription_expires_at,
                        )
                        await self._sync_white_state(
                            session,
                            user=user,
                            expires_at=subscription_expires_at,
                        )
                    if event.event_name == "new_subscription" and status == "ACTIVE":
                        _, _, effective_device_limit = await self._calculate_device_limits(session, user=user)
                        result.notification_telegram_user_id = user.telegram_user_id
                        result.notification_text = self._build_device_addon_notification_text(
                            added_devices=device_addon_bonus,
                            effective_device_limit=effective_device_limit or user.device_limit,
                            base_subscription_active=subscription_expires_at is not None,
                        )
                else:
                    existing_subscription = await self.subscriptions.get_subscription(
                        session,
                        event.telegram_user_id,
                    )
                    if existing_subscription and existing_subscription.source == "promo":
                        user.device_limit = self.settings.remnawave_default_device_limit
                    await self.subscriptions.upsert_subscription(
                        session,
                        telegram_user_id=user.telegram_user_id,
                        tribute_subscription_id=event.tribute_subscription_id,
                        period_id=event.period_id,
                        channel_id=event.channel_id,
                        status=status,
                        expires_at=expires_at,
                        cancelled=event.cancelled,
                        source="tribute",
                    )
                    await self._sync_regular_account(
                        session,
                        user=user,
                        expires_at=expires_at if expires_at and expires_at > datetime.now(UTC) else None,
                    )
                    await self._sync_white_state(
                        session,
                        user=user,
                        expires_at=expires_at if expires_at and expires_at > datetime.now(UTC) else None,
                    )

            if event.event_name == "new_donation" and event.telegram_user_id is not None:
                granted_bytes = self._resolve_white_topup_granted_bytes(
                    amount_minor=event.amount_minor,
                    currency=event.currency,
                )
                if granted_bytes is not None:
                    user = await self.users.upsert_user(
                        session,
                        telegram_user_id=event.telegram_user_id,
                        telegram_username=event.telegram_username,
                        first_name=None,
                        language_code=None,
                        is_admin=event.telegram_user_id in self.settings.bot_admin_ids,
                        device_limit=None,
                        preserve_missing_fields=True,
                    )
                    donation_order_uuid = self._white_donation_order_uuid(event)
                    order = await self.white_topup_orders.get_by_order_uuid(session, donation_order_uuid)
                    if order is None:
                        order = await self.white_topup_orders.create(
                            session,
                            telegram_user_id=user.telegram_user_id,
                            order_uuid=donation_order_uuid,
                            granted_bytes=granted_bytes,
                            amount_minor=event.amount_minor or 0,
                            currency=event.currency or "rub",
                            title=(
                                f"{self.settings.bot_public_name} White "
                                f"{self._format_white_topup_gigabytes(granted_bytes)} GB"
                            ),
                            status=event.event_name,
                            payment_url=None,
                            webapp_payment_url=None,
                            payload_json=self.tribute.dump_payload(payload),
                        )
                    order.status = event.event_name
                    order.payload_json = self.tribute.dump_payload(payload)
                    if order.paid_at is None:
                        order.paid_at = datetime.now(UTC)
                    subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
                    expires_at = ensure_utc(subscription.expires_at) if subscription else None
                    white_access = await self._sync_white_state(
                        session,
                        user=user,
                        expires_at=expires_at if subscription_is_active(subscription) else None,
                    )
                    result.notification_telegram_user_id = user.telegram_user_id
                    result.notification_text = self._build_white_topup_notification_text(
                        amount_minor=event.amount_minor or 0,
                        granted_bytes=granted_bytes,
                        white_access=white_access,
                    )

            await self.webhook_events.store(
                session,
                event_key=event.event_key,
                event_name=event.event_name,
                payload_json=self.tribute.dump_payload(payload),
            )

        return result

    async def admin_grant_white_traffic(
        self,
        *,
        lookup: str,
        gigabytes: int,
        granted_by_admin: int,
    ) -> AccessBundle | None:
        normalized = _normalize_admin_lookup(lookup)
        if not normalized or gigabytes <= 0:
            return None

        async with session_scope(self.session_factory) as session:
            user = await self._resolve_user_lookup(session, normalized)
            if user is None:
                return None

            order = await self.white_topup_orders.create(
                session,
                telegram_user_id=user.telegram_user_id,
                order_uuid=f"admin:{uuid4().hex}",
                granted_bytes=gigabytes * BYTES_PER_GB,
                amount_minor=0,
                currency="rub",
                title=f"{self.settings.bot_public_name} White {gigabytes} GB",
                status="admin_manual",
                payment_url=None,
                webapp_payment_url=None,
                payload_json=json.dumps(
                    {
                        "granted_by_admin": granted_by_admin,
                        "gigabytes": gigabytes,
                        "source": "admin_manual",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            order.paid_at = datetime.now(UTC)

            subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, user.telegram_user_id)
            expires_at = ensure_utc(subscription.expires_at) if subscription else None
            await self._sync_white_state(
                session,
                user=user,
                expires_at=expires_at if subscription_is_active(subscription) else None,
            )
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def admin_get_stats(self) -> DashboardStats:
        async with session_scope(self.session_factory) as session:
            return await self.users.get_stats(session)

    async def admin_find_user(self, telegram_user_id: int) -> AccessBundle:
        return await self.get_access_bundle(telegram_user_id)

    async def admin_find_user_by_lookup(self, lookup: str) -> AccessBundle:
        normalized = _normalize_admin_lookup(lookup)
        if not normalized:
            return AccessBundle(**user_view_model(None, None, None), base_device_limit=None, device_addon_bonus=0, effective_device_limit=None)

        async with session_scope(self.session_factory) as session:
            user = await self._resolve_user_lookup(session, normalized)
            if user is None:
                return AccessBundle(**user_view_model(None, None, None), base_device_limit=None, device_addon_bonus=0, effective_device_limit=None)
            subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, user.telegram_user_id)
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def admin_count_users(self, *, active_only: bool = False) -> int:
        async with session_scope(self.session_factory) as session:
            return await self.users.count_users(session, active_only=active_only)

    async def admin_list_users(
        self,
        *,
        active_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[AdminUserRow]:
        async with session_scope(self.session_factory) as session:
            return await self.users.list_users(
                session,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )

    async def admin_list_webhooks(self, *, limit: int = 20) -> list[WebhookEventRow]:
        async with session_scope(self.session_factory) as session:
            return await self.webhook_events.list_recent(session, limit=limit)

    async def admin_extend_access(self, *, lookup: str, days: int) -> AccessBundle | None:
        normalized = _normalize_admin_lookup(lookup)
        if not normalized or days <= 0:
            return None

        async with session_scope(self.session_factory) as session:
            user = await self._resolve_user_lookup(session, normalized)
            if user is None:
                return None

            subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
            current_expiry = ensure_utc(subscription.expires_at) if subscription else None
            base_expiry = current_expiry if current_expiry and current_expiry > datetime.now(UTC) else datetime.now(UTC)
            new_expires_at = base_expiry + timedelta(days=days)

            subscription = await self.subscriptions.upsert_subscription(
                session,
                telegram_user_id=user.telegram_user_id,
                tribute_subscription_id=subscription.tribute_subscription_id if subscription else None,
                period_id=subscription.period_id if subscription else None,
                channel_id=subscription.channel_id if subscription else None,
                status="ACTIVE",
                expires_at=new_expires_at,
                cancelled=False,
                source=subscription.source if subscription else "manual",
            )
            vpn_account = await self._sync_regular_account(
                session,
                user=user,
                expires_at=new_expires_at,
            )
            await self._sync_white_state(
                session,
                user=user,
                expires_at=new_expires_at,
            )
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def admin_update_device_limit(
        self,
        *,
        lookup: str,
        device_limit: int,
    ) -> AccessBundle | None:
        normalized = _normalize_admin_lookup(lookup)
        if not normalized or device_limit <= 0:
            return None

        async with session_scope(self.session_factory) as session:
            user = await self._resolve_user_lookup(session, normalized)
            if user is None:
                return None

            user.device_limit = device_limit
            subscription = await self.subscriptions.get_subscription(session, user.telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, user.telegram_user_id)
            expires_at = ensure_utc(subscription.expires_at) if subscription else None
            if expires_at and expires_at > datetime.now(UTC):
                vpn_account = await self._sync_regular_account(
                    session,
                    user=user,
                    expires_at=expires_at,
                )
                await self._sync_white_state(
                    session,
                    user=user,
                    expires_at=expires_at,
                )
            return await self._build_access_bundle(
                session,
                user=user,
                subscription=subscription,
                vpn_account=vpn_account,
            )

    async def admin_count_promo_redemptions(self, *, code: str) -> int:
        normalized_code = normalize_promo_code(code)
        if not normalized_code:
            return 0
        async with session_scope(self.session_factory) as session:
            return await self.promo_redemptions.count_by_code(session, code=normalized_code)

    async def admin_list_broadcast_user_ids(
        self,
        *,
        code: str | None = None,
        active_only: bool = False,
    ) -> list[int]:
        async with session_scope(self.session_factory) as session:
            if active_only:
                return await self.users.list_active_telegram_user_ids(session)
            if code is None:
                return await self.users.list_telegram_user_ids(session)
            normalized_code = normalize_promo_code(code)
            if not normalized_code:
                return []
            return await self.promo_redemptions.list_telegram_user_ids_by_code(
                session,
                code=normalized_code,
            )

    async def admin_sync_white_for_active_users(self) -> tuple[int, int, int]:
        if not self._white_feature_enabled():
            raise PermissionError("White contour is not configured")

        total = 0
        synced = 0
        failed = 0

        async with session_scope(self.session_factory) as session:
            telegram_user_ids = await self.users.list_active_telegram_user_ids(session)
            total = len(telegram_user_ids)
            for telegram_user_id in telegram_user_ids:
                user = await self.users.get_user(session, telegram_user_id)
                subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
                expires_at = ensure_utc(subscription.expires_at) if subscription else None
                if user is None or expires_at is None:
                    failed += 1
                    continue
                try:
                    await self._sync_white_state(
                        session,
                        user=user,
                        expires_at=expires_at,
                    )
                    synced += 1
                except Exception:
                    failed += 1

        return total, synced, failed

    async def admin_manual_import(
        self,
        *,
        telegram_user_id: int,
        expires_at: datetime,
        device_limit: int | None,
        note: str | None,
        imported_by_admin: int,
    ) -> AccessBundle:
        async with session_scope(self.session_factory) as session:
            return await self._grant_active_subscription(
                session,
                telegram_user_id=telegram_user_id,
                telegram_username=None,
                first_name=None,
                language_code=None,
                expires_at=expires_at,
                device_limit=device_limit,
                source="manual",
                imported_by_admin=imported_by_admin,
                note=note,
            )

    async def admin_create_promo_code(
        self,
        *,
        code: str,
        duration_days: int,
        max_usages: int,
    ) -> bool:
        normalized_code = normalize_promo_code(code)
        if not normalized_code:
            return False
        async with session_scope(self.session_factory) as session:
            promo_code = await self.promo_codes.create(
                session,
                code=normalized_code,
                duration_days=duration_days,
                max_usages=max_usages,
            )
            return promo_code is not None

    async def redeem_promo_code(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        language_code: str | None,
        code: str,
    ) -> AccessBundle | None:
        normalized_code = normalize_promo_code(code)
        if not normalized_code:
            return None

        async with session_scope(self.session_factory) as session:
            existing_subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            if subscription_is_active(existing_subscription):
                user = await self.users.get_user(session, telegram_user_id)
                vpn_account = await self.vpn_accounts.get_account(session, telegram_user_id)
                return await self._build_access_bundle(
                    session,
                    user=user,
                    subscription=existing_subscription,
                    vpn_account=vpn_account,
                )

            promo_code = await self.promo_codes.get_by_code(session, normalized_code)
            if promo_code is None:
                return None
            if not promo_code.is_active or promo_code.used_count >= promo_code.max_usages:
                return None
            if await self.promo_redemptions.has_user_redeemed(
                session,
                promo_code_id=promo_code.id,
                telegram_user_id=telegram_user_id,
            ):
                return None

            expires_at = datetime.now(UTC) + timedelta(days=promo_code.duration_days)
            await self.promo_redemptions.add(
                session,
                promo_code_id=promo_code.id,
                telegram_user_id=telegram_user_id,
                expires_at=expires_at,
            )
            await self.promo_codes.increment_usage(promo_code)
            return await self._grant_active_subscription(
                session,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                first_name=first_name,
                language_code=language_code,
                expires_at=expires_at,
                device_limit=PROMO_DEVICE_LIMIT,
                source="promo",
            )

    async def admin_delete_user(self, telegram_user_id: int) -> bool:
        regular_remote, white_remote = await self.remnawave.disable_all_access(telegram_user_id)

        async with session_scope(self.session_factory) as session:
            deleted_manual_imports = await self.manual_imports.delete_for_user(session, telegram_user_id)
            deleted_white_cycles = await self.white_traffic_cycles.delete_for_user(session, telegram_user_id)
            deleted_white_orders = await self.white_topup_orders.delete_for_user(session, telegram_user_id)
            deleted_device_addons = await self.device_addon_subscriptions.delete_for_user(session, telegram_user_id)
            deleted_white_account = await self.white_vpn_accounts.delete_account(session, telegram_user_id)
            deleted_account = await self.vpn_accounts.delete_account(session, telegram_user_id)
            deleted_subscription = await self.subscriptions.delete_subscription(session, telegram_user_id)
            deleted_user = await self.users.delete_user(session, telegram_user_id)
            return any(
                (
                    regular_remote is not None,
                    white_remote is not None,
                    bool(deleted_manual_imports),
                    bool(deleted_white_cycles),
                    bool(deleted_white_orders),
                    bool(deleted_device_addons),
                    deleted_white_account,
                    deleted_account,
                    deleted_subscription,
                    deleted_user,
                )
            )

    async def _resolve_user_lookup(self, session: AsyncSession, lookup: str) -> Any | None:
        if lookup.isdigit():
            return await self.users.search_by_telegram_id(session, int(lookup))
        normalized_username = normalize_telegram_username(lookup)
        if not normalized_username:
            return None
        return await self.users.search_by_telegram_username(session, normalized_username)
