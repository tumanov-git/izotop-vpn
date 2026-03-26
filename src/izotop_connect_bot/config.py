from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    app_base_url: str = Field(default="http://127.0.0.1:8080", alias="APP_BASE_URL")

    bot_token: str = Field(alias="BOT_TOKEN")
    bot_public_name: str = Field(default="Izotop Connect", alias="BOT_PUBLIC_NAME")
    bot_support_url: str = Field(alias="BOT_SUPPORT_URL")
    bot_faq_url: str = Field(alias="BOT_FAQ_URL")
    bot_buy_url: str = Field(alias="BOT_BUY_URL")
    bot_admin_ids: tuple[int, ...] = Field(default_factory=tuple, alias="BOT_ADMIN_IDS")

    tribute_webhook_secret: str = Field(alias="TRIBUTE_WEBHOOK_SECRET")
    tribute_signature_header: str = Field(default="trbt-signature", alias="TRIBUTE_SIGNATURE_HEADER")

    remnawave_base_url: str = Field(alias="REMNAWAVE_BASE_URL")
    remnawave_token: str = Field(alias="REMNAWAVE_TOKEN")
    remnawave_internal_squad_uuid: str | None = Field(
        default=None, alias="REMNAWAVE_INTERNAL_SQUAD_UUID"
    )
    remnawave_external_squad_uuid: str | None = Field(
        default=None, alias="REMNAWAVE_EXTERNAL_SQUAD_UUID"
    )
    remnawave_user_prefix: str = Field(default="tg", alias="REMNAWAVE_USER_PREFIX")
    remnawave_ssl_ignore: bool = Field(default=False, alias="REMNAWAVE_SSL_IGNORE")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/izotop_connect.db", alias="DATABASE_URL"
    )

    @field_validator("bot_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> tuple[int, ...]:
        if value in (None, "", ()):
            return tuple()
        if isinstance(value, (list, tuple)):
            return tuple(int(item) for item in value)
        return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())

    @property
    def webhook_path(self) -> str:
        return "/webhooks/tribute"

    @property
    def subscription_mode(self) -> Literal["multi_device"]:
        return "multi_device"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

