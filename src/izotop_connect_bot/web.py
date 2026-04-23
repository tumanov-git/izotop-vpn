from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi.responses import RedirectResponse
from fastapi import FastAPI, HTTPException, Request

from izotop_connect_bot.bot.router import create_router
from izotop_connect_bot.config import Settings
from izotop_connect_bot.db import create_engine, create_session_factory, init_db
from izotop_connect_bot.links import build_happ_deeplink
from izotop_connect_bot.services.access import AccessService
from izotop_connect_bot.services.remnawave import RemnawaveService
from izotop_connect_bot.services.tribute import TributeService


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(settings.database_url)
        self.session_factory = create_session_factory(self.engine)
        self.remnawave = RemnawaveService(settings)
        self.tribute = TributeService(
            secret=settings.tribute_webhook_secret,
            signature_header=settings.tribute_signature_header,
        )
        self.access = AccessService(
            session_factory=self.session_factory,
            settings=settings,
            remnawave=self.remnawave,
            tribute=self.tribute,
        )
        self.bot = Bot(
            settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self.dp.include_router(create_router(self.access, settings))
        self.polling_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await init_db(self.engine)
        await self.bot.delete_webhook(drop_pending_updates=False)
        self.polling_task = asyncio.create_task(self.dp.start_polling(self.bot))

    async def stop(self) -> None:
        if self.polling_task:
            self.polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.polling_task
        await self.bot.session.close()
        await self.remnawave.close()
        await self.engine.dispose()


def create_app(settings: Settings) -> FastAPI:
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await state.start()
        try:
            yield
        finally:
            await state.stop()

    app = FastAPI(title="Izotop Connect Bot", lifespan=lifespan)
    app.state.container = state

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/happlink", include_in_schema=False)
    async def happ_link(link: str) -> RedirectResponse:
        parsed = urlsplit(link)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status_code=400, detail="Invalid subscription link")
        return RedirectResponse(url=build_happ_deeplink(link), status_code=307)

    @app.post(settings.webhook_path)
    async def tribute_webhook(request: Request) -> dict[str, str]:
        body = await request.body()
        try:
            result = await state.access.process_tribute_webhook(dict(request.headers), body)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if (
            not result.is_duplicate
            and result.notification_telegram_user_id is not None
            and result.notification_text
        ):
            try:
                await state.bot.send_message(
                    result.notification_telegram_user_id,
                    result.notification_text,
                )
            except Exception:
                pass
        return {"status": "accepted"}

    return app
