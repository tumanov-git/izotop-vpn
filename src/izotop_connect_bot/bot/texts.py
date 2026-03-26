from __future__ import annotations

from datetime import datetime


DEVICE_GUIDES: dict[str, dict[str, str]] = {
    "iphone": {
        "title": "iPhone",
        "body": (
            "1. Установи `v2RayTun`.\n"
            "2. Нажми `Открыть подписку`.\n"
            "3. Импортируй ссылку в приложение.\n"
            "4. Включи профиль и разреши VPN."
        ),
    },
    "android": {
        "title": "Android",
        "body": (
            "1. Установи `v2rayNG`.\n"
            "2. Открой подписку по ссылке.\n"
            "3. Импортируй профиль.\n"
            "4. Подключись через созданную запись."
        ),
    },
    "windows": {
        "title": "Windows",
        "body": (
            "1. Установи `Hiddify Next` или другой совместимый клиент.\n"
            "2. Импортируй `subscription URL`.\n"
            "3. Выбери сервер `Netherlands`.\n"
            "4. Подключись."
        ),
    },
    "macos": {
        "title": "macOS",
        "body": (
            "1. Установи `v2RayTun` или `Hiddify Next`.\n"
            "2. Импортируй подписку.\n"
            "3. Разреши VPN-профиль.\n"
            "4. Подключись к нужному хосту."
        ),
    },
    "smart_tv": {
        "title": "Smart TV",
        "body": (
            "1. Установи совместимый клиент для Android TV.\n"
            "2. Импортируй подписку через QR или ссылку.\n"
            "3. Выбери сервер.\n"
            "4. Проверь, что трафик идёт через VPN."
        ),
    },
}


def format_expiry(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "не задана"
    return expires_at.strftime("%d.%m.%Y %H:%M UTC")


def welcome_text(name: str, *, is_active: bool, expires_at: datetime | None) -> str:
    status_line = (
        f"<b>Статус:</b> активен до {format_expiry(expires_at)}"
        if is_active
        else "<b>Статус:</b> подписка не найдена или уже истекла"
    )
    return (
        f"Привет, <b>{name}</b>.\n\n"
        f"Добро пожаловать в <b>Izotop Connect</b>.\n"
        "Здесь ты можешь получить приватный VPN-доступ, посмотреть свои ключи, "
        "быстро открыть инструкцию по устройству и написать в поддержку.\n\n"
        f"{status_line}"
    )


def keys_text(*, expires_at: datetime | None, subscription_url: str) -> str:
    return (
        "<b>Твой доступ готов</b>\n\n"
        f"<b>Активен до:</b> {format_expiry(expires_at)}\n"
        f"<b>Subscription URL:</b>\n<code>{subscription_url}</code>\n\n"
        "Используй кнопку ниже или QR-код, чтобы импортировать подписку в клиент."
    )


def inactive_access_text() -> str:
    return (
        "Сейчас у тебя нет активной подписки.\n\n"
        "Если доступ уже должен быть активен, нажми <b>Проверить подписку</b> или напиши в поддержку."
    )


def admin_stats_text(total_users: int, active_subscriptions: int, vpn_accounts: int, webhooks: int) -> str:
    return (
        "<b>Админка Izotop Connect</b>\n\n"
        f"Пользователи: <b>{total_users}</b>\n"
        f"Активные подписки: <b>{active_subscriptions}</b>\n"
        f"VPN-аккаунты: <b>{vpn_accounts}</b>\n"
        f"Webhook events: <b>{webhooks}</b>"
    )
