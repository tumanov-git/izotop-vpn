from __future__ import annotations

import uvicorn

from izotop_connect_bot.config import get_settings
from izotop_connect_bot.web import create_app


def run() -> None:
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)

