from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from izotop_connect_bot.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        db_path = database_url.split("///", 1)[-1]
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(database_url, future=True, echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.drivername.startswith("sqlite"):
            result = await conn.exec_driver_sql("PRAGMA table_info(users)")
            columns = {row[1] for row in result.fetchall()}
            if "device_limit" not in columns:
                await conn.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN device_limit INTEGER NOT NULL DEFAULT 3"
                )
            result = await conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='device_addon_subscriptions'"
            )
            row = result.fetchone()
            create_sql = row[0] if row else None
            if create_sql and "tribute_subscription_id BIGINT NOT NULL" in create_sql:
                await conn.exec_driver_sql("ALTER TABLE device_addon_subscriptions RENAME TO device_addon_subscriptions_legacy")
                await conn.run_sync(Base.metadata.create_all)
                await conn.exec_driver_sql(
                    """
                    INSERT INTO device_addon_subscriptions (
                        telegram_user_id,
                        tribute_subscription_id,
                        subscription_name,
                        period_id,
                        channel_id,
                        bonus_devices,
                        status,
                        expires_at,
                        cancelled,
                        source,
                        updated_at
                    )
                    SELECT
                        telegram_user_id,
                        tribute_subscription_id,
                        subscription_name,
                        period_id,
                        channel_id,
                        bonus_devices,
                        status,
                        expires_at,
                        cancelled,
                        source,
                        updated_at
                    FROM device_addon_subscriptions_legacy
                    """
                )
                await conn.exec_driver_sql("DROP TABLE device_addon_subscriptions_legacy")


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
