from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from remnawave import RemnawaveSDK
from remnawave.enums.users import TrafficLimitStrategy, UserStatus
from remnawave.models import CreateUserRequestDto, UpdateUserRequestDto

from izotop_connect_bot.config import Settings


class RemnawaveService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sdk = RemnawaveSDK(
            base_url=settings.remnawave_base_url,
            token=settings.remnawave_token,
            ssl_ignore=settings.remnawave_ssl_ignore,
        )

    async def close(self) -> None:
        await self.sdk._client.aclose()

    def build_username(self, telegram_user_id: int) -> str:
        return f"{self.settings.remnawave_user_prefix}_{telegram_user_id}"

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> Any | None:
        response = await self.sdk.users.get_users_by_telegram_id(str(telegram_user_id))
        return response[0] if len(response) else None

    async def ensure_user(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime,
    ) -> Any:
        expires_at = expires_at.astimezone(UTC)
        remote_user = await self.get_user_by_telegram_id(telegram_user_id)
        description = f"Telegram: @{telegram_username}" if telegram_username else first_name or "Telegram user"
        active_internal_squads = []
        if self.settings.remnawave_internal_squad_uuid:
            active_internal_squads = [UUID(self.settings.remnawave_internal_squad_uuid)]
        external_squad_uuid = (
            UUID(self.settings.remnawave_external_squad_uuid)
            if self.settings.remnawave_external_squad_uuid
            else None
        )

        if remote_user is None:
            request = CreateUserRequestDto(
                username=self.build_username(telegram_user_id),
                expire_at=expires_at,
                telegram_id=telegram_user_id,
                description=description,
                status=UserStatus.ACTIVE,
                traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
                active_internal_squads=active_internal_squads or None,
                external_squad_uuid=external_squad_uuid,
            )
            return await self.sdk.users.create_user(request)

        request = UpdateUserRequestDto(
            uuid=remote_user.uuid,
            telegram_id=telegram_user_id,
            description=description,
            expire_at=expires_at,
            status=UserStatus.ACTIVE,
            active_internal_squads=active_internal_squads or None,
            external_squad_uuid=external_squad_uuid,
        )
        return await self.sdk.users.update_user(request)

    async def disable_user(self, user_uuid: str) -> None:
        await self.sdk.users.disable_user(user_uuid)

    async def sync_access(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime | None,
    ) -> Any | None:
        if expires_at is None:
            remote = await self.get_user_by_telegram_id(telegram_user_id)
            if remote:
                await self.disable_user(str(remote.uuid))
            return remote

        if expires_at <= datetime.now(UTC):
            remote = await self.get_user_by_telegram_id(telegram_user_id)
            if remote:
                await self.disable_user(str(remote.uuid))
            return remote

        return await self.ensure_user(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            expires_at=expires_at,
        )

    async def create_trial_extension(self, telegram_user_id: int) -> Any:
        return await self.ensure_user(
            telegram_user_id=telegram_user_id,
            telegram_username=None,
            first_name="Manual sync",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

