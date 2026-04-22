from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from izotop_connect_bot.models import (
    ManualImport,
    PromoCode,
    PromoCodeRedemption,
    Subscription,
    User,
    VpnAccount,
    WebhookEvent,
    WhiteTopUpOrder,
    WhiteTrafficCycle,
    WhiteVpnAccount,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_telegram_username(value: str) -> str:
    return value.strip().lstrip("@").casefold()


@dataclass(slots=True)
class DashboardStats:
    total_users: int
    active_subscriptions: int
    vpn_accounts: int
    processed_webhooks: int


@dataclass(slots=True)
class AdminUserRow:
    telegram_user_id: int
    telegram_username: str | None
    first_name: str | None
    device_limit: int
    is_active: bool
    expires_at: datetime | None
    has_vpn: bool
    source: str | None


@dataclass(slots=True)
class WebhookEventRow:
    event_name: str
    event_key: str
    processed_at: datetime | None


class UserRepository:
    async def count_users(
        self,
        session: AsyncSession,
        *,
        active_only: bool = False,
    ) -> int:
        if not active_only:
            return await session.scalar(select(func.count()).select_from(User)) or 0
        query = select(func.count()).select_from(Subscription).where(
            Subscription.expires_at.is_not(None),
            Subscription.expires_at > utcnow(),
        )
        return await session.scalar(query) or 0

    async def upsert_user(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        language_code: str | None,
        is_admin: bool,
        device_limit: int | None = None,
        preserve_missing_fields: bool = False,
    ) -> User:
        user = await session.get(User, telegram_user_id)
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                first_name=first_name,
                language_code=language_code,
                is_admin=is_admin,
                device_limit=device_limit or 3,
            )
            session.add(user)
        else:
            if preserve_missing_fields:
                if telegram_username is not None:
                    user.telegram_username = telegram_username
                if first_name is not None:
                    user.first_name = first_name
                if language_code is not None:
                    user.language_code = language_code
            else:
                user.telegram_username = telegram_username
                user.first_name = first_name
                user.language_code = language_code
            user.is_admin = is_admin
            if device_limit is not None:
                user.device_limit = device_limit
        return user

    async def get_user(self, session: AsyncSession, telegram_user_id: int) -> User | None:
        return await session.get(User, telegram_user_id)

    async def delete_user(self, session: AsyncSession, telegram_user_id: int) -> bool:
        user = await self.get_user(session, telegram_user_id)
        if user is None:
            return False
        await session.delete(user)
        return True

    async def search_by_telegram_id(
        self, session: AsyncSession, telegram_user_id: int
    ) -> User | None:
        query = select(User).where(User.telegram_user_id == telegram_user_id)
        return (await session.execute(query)).scalar_one_or_none()

    async def search_by_telegram_username(
        self,
        session: AsyncSession,
        telegram_username: str,
    ) -> User | None:
        normalized = normalize_telegram_username(telegram_username)
        if not normalized:
            return None
        query = select(User).where(func.lower(User.telegram_username) == normalized)
        return (await session.execute(query)).scalar_one_or_none()

    async def get_stats(self, session: AsyncSession) -> DashboardStats:
        total_users = await session.scalar(select(func.count()).select_from(User)) or 0
        subscriptions = (await session.execute(select(Subscription))).scalars().all()
        active_subscriptions = sum(1 for item in subscriptions if subscription_is_active(item))
        vpn_accounts = await session.scalar(select(func.count()).select_from(VpnAccount)) or 0
        processed_webhooks = await session.scalar(select(func.count()).select_from(WebhookEvent)) or 0
        return DashboardStats(
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            vpn_accounts=vpn_accounts,
            processed_webhooks=processed_webhooks,
        )

    async def list_users(
        self,
        session: AsyncSession,
        *,
        active_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[AdminUserRow]:
        query = select(User)
        if active_only:
            query = (
                query.join(Subscription, Subscription.telegram_user_id == User.telegram_user_id)
                .where(Subscription.expires_at.is_not(None), Subscription.expires_at > utcnow())
            )
        query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        users = (await session.execute(query)).scalars().all()
        rows: list[AdminUserRow] = []
        for user in users:
            subscription = await session.scalar(
                select(Subscription).where(Subscription.telegram_user_id == user.telegram_user_id)
            )
            vpn_account = await session.scalar(
                select(VpnAccount).where(VpnAccount.telegram_user_id == user.telegram_user_id)
            )
            is_active = subscription_is_active(subscription)
            rows.append(
                AdminUserRow(
                    telegram_user_id=user.telegram_user_id,
                    telegram_username=user.telegram_username,
                    first_name=user.first_name,
                    device_limit=user.device_limit,
                    is_active=is_active,
                    expires_at=ensure_utc(subscription.expires_at) if subscription else None,
                    has_vpn=vpn_account is not None,
                    source=subscription.source if subscription else None,
                )
            )
        return rows

    async def list_telegram_user_ids(self, session: AsyncSession) -> list[int]:
        query = select(User.telegram_user_id).order_by(User.created_at.asc(), User.telegram_user_id.asc())
        return list((await session.execute(query)).scalars().all())

    async def list_active_telegram_user_ids(self, session: AsyncSession) -> list[int]:
        query = (
            select(User.telegram_user_id)
            .join(Subscription, Subscription.telegram_user_id == User.telegram_user_id)
            .where(Subscription.expires_at.is_not(None), Subscription.expires_at > utcnow())
            .order_by(User.created_at.asc(), User.telegram_user_id.asc())
        )
        return list((await session.execute(query)).scalars().all())


class SubscriptionRepository:
    async def upsert_subscription(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        tribute_subscription_id: int | None,
        period_id: int | None,
        channel_id: int | None,
        status: str,
        expires_at: datetime | None,
        cancelled: bool,
        source: str = "tribute",
    ) -> Subscription:
        query = select(Subscription).where(Subscription.telegram_user_id == telegram_user_id)
        subscription = (await session.execute(query)).scalar_one_or_none()
        if subscription is None:
            subscription = Subscription(
                telegram_user_id=telegram_user_id,
                tribute_subscription_id=tribute_subscription_id,
                period_id=period_id,
                channel_id=channel_id,
                status=status,
                expires_at=ensure_utc(expires_at),
                cancelled=cancelled,
                source=source,
            )
            session.add(subscription)
        else:
            subscription.tribute_subscription_id = tribute_subscription_id
            subscription.period_id = period_id
            subscription.channel_id = channel_id
            subscription.status = status
            subscription.expires_at = ensure_utc(expires_at)
            subscription.cancelled = cancelled
            subscription.source = source
        return subscription

    async def get_subscription(
        self, session: AsyncSession, telegram_user_id: int
    ) -> Subscription | None:
        query = select(Subscription).where(Subscription.telegram_user_id == telegram_user_id)
        return (await session.execute(query)).scalar_one_or_none()

    async def delete_subscription(self, session: AsyncSession, telegram_user_id: int) -> bool:
        subscription = await self.get_subscription(session, telegram_user_id)
        if subscription is None:
            return False
        await session.delete(subscription)
        return True


class VpnAccountRepository:
    async def get_account(self, session: AsyncSession, telegram_user_id: int) -> VpnAccount | None:
        query = select(VpnAccount).where(VpnAccount.telegram_user_id == telegram_user_id)
        return (await session.execute(query)).scalar_one_or_none()

    async def delete_account(self, session: AsyncSession, telegram_user_id: int) -> bool:
        account = await self.get_account(session, telegram_user_id)
        if account is None:
            return False
        await session.delete(account)
        return True

    async def upsert_account(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        remnawave_user_uuid: str,
        remnawave_username: str,
        subscription_url: str,
    ) -> VpnAccount:
        account = await self.get_account(session, telegram_user_id)
        if account is None:
            account = VpnAccount(
                telegram_user_id=telegram_user_id,
                remnawave_user_uuid=remnawave_user_uuid,
                remnawave_username=remnawave_username,
                subscription_url=subscription_url,
                last_issued_at=utcnow(),
            )
            session.add(account)
        else:
            account.remnawave_user_uuid = remnawave_user_uuid
            account.remnawave_username = remnawave_username
            account.subscription_url = subscription_url
            account.last_issued_at = utcnow()
        return account


class WhiteVpnAccountRepository:
    async def get_account(self, session: AsyncSession, telegram_user_id: int) -> WhiteVpnAccount | None:
        query = select(WhiteVpnAccount).where(WhiteVpnAccount.telegram_user_id == telegram_user_id)
        return (await session.execute(query)).scalar_one_or_none()

    async def delete_account(self, session: AsyncSession, telegram_user_id: int) -> bool:
        account = await self.get_account(session, telegram_user_id)
        if account is None:
            return False
        await session.delete(account)
        return True

    async def upsert_account(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        remnawave_user_uuid: str,
        remnawave_username: str,
        subscription_url: str,
    ) -> WhiteVpnAccount:
        account = await self.get_account(session, telegram_user_id)
        if account is None:
            account = WhiteVpnAccount(
                telegram_user_id=telegram_user_id,
                remnawave_user_uuid=remnawave_user_uuid,
                remnawave_username=remnawave_username,
                subscription_url=subscription_url,
                last_issued_at=utcnow(),
            )
            session.add(account)
        else:
            account.remnawave_user_uuid = remnawave_user_uuid
            account.remnawave_username = remnawave_username
            account.subscription_url = subscription_url
            account.last_issued_at = utcnow()
        return account


class WhiteTrafficCycleRepository:
    async def get_latest_cycle(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> WhiteTrafficCycle | None:
        query = (
            select(WhiteTrafficCycle)
            .where(WhiteTrafficCycle.telegram_user_id == telegram_user_id)
            .order_by(WhiteTrafficCycle.expires_at.desc(), WhiteTrafficCycle.id.desc())
            .limit(1)
        )
        return (await session.execute(query)).scalar_one_or_none()

    async def get_active_cycle(
        self,
        session: AsyncSession,
        telegram_user_id: int,
        *,
        at: datetime | None = None,
    ) -> WhiteTrafficCycle | None:
        point = ensure_utc(at) or utcnow()
        query = (
            select(WhiteTrafficCycle)
            .where(
                WhiteTrafficCycle.telegram_user_id == telegram_user_id,
                WhiteTrafficCycle.started_at <= point,
                WhiteTrafficCycle.expires_at > point,
            )
            .order_by(WhiteTrafficCycle.started_at.desc(), WhiteTrafficCycle.id.desc())
            .limit(1)
        )
        return (await session.execute(query)).scalar_one_or_none()

    async def list_cycles(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> list[WhiteTrafficCycle]:
        query = (
            select(WhiteTrafficCycle)
            .where(WhiteTrafficCycle.telegram_user_id == telegram_user_id)
            .order_by(WhiteTrafficCycle.started_at.asc(), WhiteTrafficCycle.id.asc())
        )
        return list((await session.execute(query)).scalars().all())

    async def create_cycle(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        started_at: datetime,
        expires_at: datetime,
        free_bytes: int,
        start_used_bytes: int | None,
    ) -> WhiteTrafficCycle:
        cycle = WhiteTrafficCycle(
            telegram_user_id=telegram_user_id,
            started_at=ensure_utc(started_at),
            expires_at=ensure_utc(expires_at),
            free_bytes=free_bytes,
            start_used_bytes=start_used_bytes,
            end_used_bytes=None,
        )
        session.add(cycle)
        return cycle

    async def delete_for_user(self, session: AsyncSession, telegram_user_id: int) -> int:
        query = select(WhiteTrafficCycle).where(WhiteTrafficCycle.telegram_user_id == telegram_user_id)
        rows = (await session.execute(query)).scalars().all()
        for row in rows:
            await session.delete(row)
        return len(rows)


class WhiteTopUpOrderRepository:
    PAID_STATUSES = {"paid", "shop_order", "shop_order_charge_success", "new_donation", "recurrent_donation", "admin_manual"}

    async def get_by_order_uuid(
        self,
        session: AsyncSession,
        order_uuid: str,
    ) -> WhiteTopUpOrder | None:
        query = select(WhiteTopUpOrder).where(WhiteTopUpOrder.order_uuid == order_uuid)
        return (await session.execute(query)).scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        order_uuid: str,
        granted_bytes: int,
        amount_minor: int,
        currency: str,
        title: str,
        status: str,
        payment_url: str | None,
        webapp_payment_url: str | None,
        payload_json: str | None,
    ) -> WhiteTopUpOrder:
        order = WhiteTopUpOrder(
            telegram_user_id=telegram_user_id,
            order_uuid=order_uuid,
            granted_bytes=granted_bytes,
            amount_minor=amount_minor,
            currency=currency,
            title=title,
            status=status,
            payment_url=payment_url,
            webapp_payment_url=webapp_payment_url,
            payload_json=payload_json,
        )
        session.add(order)
        return order

    async def list_for_user(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> list[WhiteTopUpOrder]:
        query = (
            select(WhiteTopUpOrder)
            .where(WhiteTopUpOrder.telegram_user_id == telegram_user_id)
            .order_by(WhiteTopUpOrder.created_at.asc(), WhiteTopUpOrder.id.asc())
        )
        return list((await session.execute(query)).scalars().all())

    async def sum_paid_bytes(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> int:
        query = (
            select(func.coalesce(func.sum(WhiteTopUpOrder.granted_bytes), 0))
            .where(
                WhiteTopUpOrder.telegram_user_id == telegram_user_id,
                func.lower(WhiteTopUpOrder.status).in_(self.PAID_STATUSES),
            )
        )
        return int(await session.scalar(query) or 0)

    async def delete_for_user(self, session: AsyncSession, telegram_user_id: int) -> int:
        query = select(WhiteTopUpOrder).where(WhiteTopUpOrder.telegram_user_id == telegram_user_id)
        rows = (await session.execute(query)).scalars().all()
        for row in rows:
            await session.delete(row)
        return len(rows)


class WebhookEventRepository:
    async def exists(self, session: AsyncSession, event_key: str) -> bool:
        query = select(WebhookEvent.id).where(WebhookEvent.event_key == event_key)
        return (await session.execute(query)).scalar_one_or_none() is not None

    async def store(
        self, session: AsyncSession, *, event_key: str, event_name: str, payload_json: str
    ) -> WebhookEvent:
        event = WebhookEvent(event_key=event_key, event_name=event_name, payload_json=payload_json)
        session.add(event)
        return event

    async def list_recent(
        self, session: AsyncSession, *, limit: int = 20
    ) -> list[WebhookEventRow]:
        query = (
            select(WebhookEvent)
            .order_by(WebhookEvent.processed_at.desc(), WebhookEvent.id.desc())
            .limit(limit)
        )
        events = (await session.execute(query)).scalars().all()
        return [
            WebhookEventRow(
                event_name=event.event_name,
                event_key=event.event_key,
                processed_at=ensure_utc(event.processed_at),
            )
            for event in events
        ]


class ManualImportRepository:
    async def add(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        expires_at: datetime,
        note: str | None,
        imported_by_admin: int | None,
    ) -> ManualImport:
        item = ManualImport(
            telegram_user_id=telegram_user_id,
            expires_at=ensure_utc(expires_at),
            note=note,
            imported_by_admin=imported_by_admin,
        )
        session.add(item)
        return item

    async def delete_for_user(self, session: AsyncSession, telegram_user_id: int) -> int:
        query = select(ManualImport).where(ManualImport.telegram_user_id == telegram_user_id)
        items = (await session.execute(query)).scalars().all()
        for item in items:
            await session.delete(item)
        return len(items)


class PromoCodeRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        code: str,
        duration_days: int,
        max_usages: int,
    ) -> PromoCode | None:
        existing = await self.get_by_code(session, code)
        if existing is not None:
            return None
        promo_code = PromoCode(
            code=code,
            duration_days=duration_days,
            max_usages=max_usages,
            used_count=0,
            is_active=True,
        )
        session.add(promo_code)
        return promo_code

    async def get_by_code(self, session: AsyncSession, code: str) -> PromoCode | None:
        query = select(PromoCode).where(PromoCode.code == code)
        return (await session.execute(query)).scalar_one_or_none()

    async def has_available_uses(self, promo_code: PromoCode) -> bool:
        return promo_code.is_active and promo_code.used_count < promo_code.max_usages

    async def increment_usage(self, promo_code: PromoCode) -> PromoCode:
        promo_code.used_count += 1
        return promo_code


class PromoCodeRedemptionRepository:
    async def count_by_code(
        self,
        session: AsyncSession,
        *,
        code: str,
    ) -> int:
        query = (
            select(func.count())
            .select_from(PromoCodeRedemption)
            .join(PromoCode, PromoCode.id == PromoCodeRedemption.promo_code_id)
            .where(PromoCode.code == code)
        )
        return await session.scalar(query) or 0

    async def has_user_redeemed(
        self,
        session: AsyncSession,
        *,
        promo_code_id: int,
        telegram_user_id: int,
    ) -> bool:
        query = select(PromoCodeRedemption.id).where(
            PromoCodeRedemption.promo_code_id == promo_code_id,
            PromoCodeRedemption.telegram_user_id == telegram_user_id,
        )
        return (await session.execute(query)).scalar_one_or_none() is not None

    async def add(
        self,
        session: AsyncSession,
        *,
        promo_code_id: int,
        telegram_user_id: int,
        expires_at: datetime,
    ) -> PromoCodeRedemption:
        redemption = PromoCodeRedemption(
            promo_code_id=promo_code_id,
            telegram_user_id=telegram_user_id,
            expires_at=ensure_utc(expires_at),
        )
        session.add(redemption)
        return redemption

    async def list_telegram_user_ids_by_code(
        self,
        session: AsyncSession,
        *,
        code: str,
    ) -> list[int]:
        query = (
            select(PromoCodeRedemption.telegram_user_id)
            .join(PromoCode, PromoCode.id == PromoCodeRedemption.promo_code_id)
            .where(PromoCode.code == code)
            .order_by(PromoCodeRedemption.redeemed_at.asc(), PromoCodeRedemption.telegram_user_id.asc())
        )
        return list((await session.execute(query)).scalars().all())


def subscription_is_active(subscription: Subscription | None) -> bool:
    if subscription is None or subscription.expires_at is None:
        return False
    expires_at = ensure_utc(subscription.expires_at)
    return bool(expires_at and expires_at > utcnow())


def user_view_model(
    user: User | None,
    subscription: Subscription | None,
    vpn_account: VpnAccount | None,
) -> dict[str, Any]:
    is_active = subscription_is_active(subscription)
    return {
        "user": user,
        "subscription": subscription,
        "vpn_account": vpn_account,
        "is_active": is_active,
        "expires_at": ensure_utc(subscription.expires_at) if subscription else None,
    }
