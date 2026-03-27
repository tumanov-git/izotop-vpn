from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from izotop_connect_bot.models import ManualImport, Subscription, User, VpnAccount, WebhookEvent


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    ) -> list[AdminUserRow]:
        query = select(User).order_by(User.created_at.desc()).limit(limit)
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
            if active_only and not is_active:
                continue
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
