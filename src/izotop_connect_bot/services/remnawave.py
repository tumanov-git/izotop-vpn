from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from remnawave import RemnawaveSDK
from remnawave.enums.users import TrafficLimitStrategy, UserStatus
from remnawave.models import CreateUserRequestDto, UpdateUserRequestDto

from izotop_connect_bot.config import Settings


@dataclass(frozen=True, slots=True)
class RemnawaveProfile:
    username: str
    internal_squad_uuid: str | None
    external_squad_uuid: str | None


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

    def build_white_username(self, telegram_user_id: int) -> str:
        return f"{self.settings.remnawave_white_user_prefix}_{telegram_user_id}"

    def regular_profile(self, telegram_user_id: int) -> RemnawaveProfile:
        return RemnawaveProfile(
            username=self.build_username(telegram_user_id),
            internal_squad_uuid=self.settings.remnawave_internal_squad_uuid,
            external_squad_uuid=self.settings.remnawave_external_squad_uuid,
        )

    def white_profile(self, telegram_user_id: int) -> RemnawaveProfile:
        return RemnawaveProfile(
            username=self.build_white_username(telegram_user_id),
            internal_squad_uuid=self.settings.remnawave_white_internal_squad_uuid,
            external_squad_uuid=self.settings.remnawave_white_external_squad_uuid,
        )

    async def get_user_by_username(self, username: str) -> Any | None:
        try:
            return await self.sdk.users.get_user_by_username(username)
        except Exception:
            return None

    async def get_regular_user(self, telegram_user_id: int) -> Any | None:
        return await self.get_user_by_username(self.build_username(telegram_user_id))

    async def get_white_user(self, telegram_user_id: int) -> Any | None:
        return await self.get_user_by_username(self.build_white_username(telegram_user_id))

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> Any | None:
        return await self.get_regular_user(telegram_user_id)

    @staticmethod
    def extract_used_traffic_bytes(remote_user: Any | None) -> int:
        if remote_user is None:
            return 0
        direct_value = getattr(remote_user, "used_traffic_bytes", None)
        if isinstance(direct_value, int):
            return max(0, direct_value)
        user_traffic = getattr(remote_user, "user_traffic", None)
        nested_value = getattr(user_traffic, "used_traffic_bytes", None)
        if isinstance(nested_value, int):
            return max(0, nested_value)
        return 0

    async def ensure_user(
        self,
        *,
        profile: RemnawaveProfile,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime,
        device_limit: int,
        traffic_limit_bytes: int | None = None,
    ) -> Any:
        expires_at = expires_at.astimezone(UTC)
        remote_user = await self.get_user_by_username(profile.username)
        description = f"Telegram: @{telegram_username}" if telegram_username else first_name or "Telegram user"
        active_internal_squads = []
        if profile.internal_squad_uuid:
            active_internal_squads = [UUID(profile.internal_squad_uuid)]
        external_squad_uuid = UUID(profile.external_squad_uuid) if profile.external_squad_uuid else None

        if remote_user is None:
            request = CreateUserRequestDto(
                username=profile.username,
                expire_at=expires_at,
                telegram_id=telegram_user_id,
                description=description,
                status=UserStatus.ACTIVE,
                traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
                traffic_limit_bytes=traffic_limit_bytes,
                hwid_device_limit=device_limit,
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
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            traffic_limit_bytes=traffic_limit_bytes,
            hwid_device_limit=device_limit,
            active_internal_squads=active_internal_squads or None,
            external_squad_uuid=external_squad_uuid,
        )
        return await self.sdk.users.update_user(request)

    async def disable_user(self, user_uuid: str) -> None:
        await self.sdk.users.disable_user(user_uuid)

    async def disable_profile(self, username: str) -> Any | None:
        remote = await self.get_user_by_username(username)
        if remote is not None:
            await self.disable_user(str(remote.uuid))
        return remote

    async def sync_profile(
        self,
        *,
        profile: RemnawaveProfile,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime | None,
        device_limit: int,
        traffic_limit_bytes: int | None = None,
    ) -> Any | None:
        if expires_at is None or expires_at <= datetime.now(UTC):
            return await self.disable_profile(profile.username)

        return await self.ensure_user(
            profile=profile,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            expires_at=expires_at,
            device_limit=device_limit,
            traffic_limit_bytes=traffic_limit_bytes,
        )

    async def sync_access(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime | None,
        device_limit: int,
    ) -> Any | None:
        return await self.sync_profile(
            profile=self.regular_profile(telegram_user_id),
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            expires_at=expires_at,
            device_limit=device_limit,
        )

    async def sync_white_access(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        first_name: str | None,
        expires_at: datetime | None,
        device_limit: int,
        traffic_limit_bytes: int | None,
    ) -> Any | None:
        if not self.settings.remnawave_white_internal_squad_uuid:
            return None
        return await self.sync_profile(
            profile=self.white_profile(telegram_user_id),
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            expires_at=expires_at,
            device_limit=device_limit,
            traffic_limit_bytes=traffic_limit_bytes,
        )

    async def disable_all_access(self, telegram_user_id: int) -> tuple[Any | None, Any | None]:
        regular = await self.disable_profile(self.build_username(telegram_user_id))
        white = await self.disable_profile(self.build_white_username(telegram_user_id))
        return regular, white

    async def create_trial_extension(self, telegram_user_id: int) -> Any:
        return await self.ensure_user(
            profile=self.regular_profile(telegram_user_id),
            telegram_user_id=telegram_user_id,
            telegram_username=None,
            first_name="Manual sync",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            device_limit=self.settings.remnawave_default_device_limit,
        )
