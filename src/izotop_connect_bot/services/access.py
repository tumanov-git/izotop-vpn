from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from izotop_connect_bot.config import Settings
from izotop_connect_bot.db import session_scope
from izotop_connect_bot.repositories import (
    AdminUserRow,
    DashboardStats,
    ManualImportRepository,
    SubscriptionRepository,
    UserRepository,
    VpnAccountRepository,
    WebhookEventRepository,
    WebhookEventRow,
    ensure_utc,
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
        self.webhook_events = WebhookEventRepository()
        self.manual_imports = ManualImportRepository()

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
            model = user_view_model(user, subscription, vpn_account)
            return AccessBundle(**model)

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
            return vpn_account

    async def refresh_remote_state(self, telegram_user_id: int) -> AccessBundle:
        async with session_scope(self.session_factory) as session:
            user = await self.users.get_user(session, telegram_user_id)
            subscription = await self.subscriptions.get_subscription(session, telegram_user_id)
            vpn_account = await self.vpn_accounts.get_account(session, telegram_user_id)
            expires_at = ensure_utc(subscription.expires_at) if subscription else None
            if user and subscription and expires_at:
                remote = await self.remnawave.sync_access(
                    telegram_user_id=telegram_user_id,
                    telegram_username=user.telegram_username,
                    first_name=user.first_name,
                    expires_at=expires_at if subscription_is_active(subscription) else None,
                    device_limit=user.device_limit,
                )
                if remote is not None and getattr(remote, "subscription_url", None):
                    vpn_account = await self.vpn_accounts.upsert_account(
                        session,
                        telegram_user_id=telegram_user_id,
                        remnawave_user_uuid=str(remote.uuid),
                        remnawave_username=remote.username,
                        subscription_url=remote.subscription_url,
                    )
            model = user_view_model(user, subscription, vpn_account)
            return AccessBundle(**model)

    async def process_tribute_webhook(self, headers: dict[str, str], body: bytes) -> TributeEvent:
        if not self.tribute.verify_signature(headers, body):
            raise PermissionError("Invalid Tribute signature")

        payload = __import__("json").loads(body.decode("utf-8"))
        event = self.tribute.parse_event(payload)

        async with session_scope(self.session_factory) as session:
            if await self.webhook_events.exists(session, event.event_key):
                return event

            if event.telegram_user_id is not None:
                user = await self.users.upsert_user(
                    session,
                    telegram_user_id=event.telegram_user_id,
                    telegram_username=event.telegram_username,
                    first_name=event.telegram_username,
                    language_code=None,
                    is_admin=event.telegram_user_id in self.settings.bot_admin_ids,
                    device_limit=None,
                )
                expires_at = ensure_utc(event.expires_at)
                status = "ACTIVE" if expires_at and expires_at > datetime.now(UTC) else "INACTIVE"
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
                if expires_at is not None:
                    remote = await self.remnawave.sync_access(
                        telegram_user_id=user.telegram_user_id,
                        telegram_username=user.telegram_username,
                        first_name=user.first_name,
                        expires_at=expires_at if expires_at > datetime.now(UTC) else None,
                        device_limit=user.device_limit,
                    )
                    if remote is not None and getattr(remote, "subscription_url", None):
                        await self.vpn_accounts.upsert_account(
                            session,
                            telegram_user_id=user.telegram_user_id,
                            remnawave_user_uuid=str(remote.uuid),
                            remnawave_username=remote.username,
                            subscription_url=remote.subscription_url,
                        )

            await self.webhook_events.store(
                session,
                event_key=event.event_key,
                event_name=event.event_name,
                payload_json=self.tribute.dump_payload(payload),
            )

        return event

    async def admin_get_stats(self) -> DashboardStats:
        async with session_scope(self.session_factory) as session:
            return await self.users.get_stats(session)

    async def admin_find_user(self, telegram_user_id: int) -> AccessBundle:
        return await self.get_access_bundle(telegram_user_id)

    async def admin_list_users(self, *, active_only: bool = False, limit: int = 25) -> list[AdminUserRow]:
        async with session_scope(self.session_factory) as session:
            return await self.users.list_users(session, active_only=active_only, limit=limit)

    async def admin_list_webhooks(self, *, limit: int = 20) -> list[WebhookEventRow]:
        async with session_scope(self.session_factory) as session:
            return await self.webhook_events.list_recent(session, limit=limit)

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
            user = await self.users.upsert_user(
                session,
                telegram_user_id=telegram_user_id,
                telegram_username=None,
                first_name=None,
                language_code=None,
                is_admin=telegram_user_id in self.settings.bot_admin_ids,
                device_limit=device_limit or self.settings.remnawave_default_device_limit,
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
                source="manual",
            )
            await self.manual_imports.add(
                session,
                telegram_user_id=telegram_user_id,
                expires_at=ensure_utc(expires_at),
                note=note,
                imported_by_admin=imported_by_admin,
            )
            remote = await self.remnawave.sync_access(
                telegram_user_id=user.telegram_user_id,
                telegram_username=user.telegram_username,
                first_name=user.first_name,
                expires_at=ensure_utc(expires_at),
                device_limit=user.device_limit,
            )
            if remote is not None and getattr(remote, "subscription_url", None):
                await self.vpn_accounts.upsert_account(
                    session,
                    telegram_user_id=user.telegram_user_id,
                    remnawave_user_uuid=str(remote.uuid),
                    remnawave_username=remote.username,
                    subscription_url=remote.subscription_url,
                )
        return await self.get_access_bundle(telegram_user_id)

    async def admin_delete_user(self, telegram_user_id: int) -> bool:
        remote = await self.remnawave.get_user_by_telegram_id(telegram_user_id)
        if remote is not None:
            await self.remnawave.disable_user(str(remote.uuid))

        async with session_scope(self.session_factory) as session:
            deleted_manual_imports = await self.manual_imports.delete_for_user(session, telegram_user_id)
            deleted_account = await self.vpn_accounts.delete_account(session, telegram_user_id)
            deleted_subscription = await self.subscriptions.delete_subscription(session, telegram_user_id)
            deleted_user = await self.users.delete_user(session, telegram_user_id)
            return any(
                (
                    remote is not None,
                    bool(deleted_manual_imports),
                    deleted_account,
                    deleted_subscription,
                    deleted_user,
                )
            )
