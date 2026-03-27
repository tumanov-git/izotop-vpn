from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Literal

from izotop_connect_bot.repositories import AdminUserRow, WebhookEventRow

SubscriptionState = Literal["new", "active", "inactive"]


DEVICE_GUIDES: dict[str, dict[str, str]] = {
    "iphone": {
        "title": "iPhone",
        "body": (
            "1. Установи <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">Happ из App Store</a>.\n"
            "2. Нажми <b>Открыть доступ</b>.\n"
            "3. Импортируй ссылку в Happ.\n"
            "4. Включи профиль и разреши VPN."
        ),
    },
    "android": {
        "title": "Android",
        "body": (
            "1. Установи <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Happ из Google Play</a>.\n"
            "2. Открой доступ по ссылке.\n"
            "3. Импортируй профиль в Happ.\n"
            "4. Подключись через созданную запись."
        ),
    },
    "windows": {
        "title": "Windows",
        "body": (
            "1. Установи <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Happ для Windows</a>.\n"
            "2. Импортируй <b>subscription URL</b>.\n"
            "3. Выбери сервер <b>Netherlands</b>.\n"
            "4. Подключись."
        ),
    },
    "macos": {
        "title": "macOS",
        "body": (
            "1. Установи <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg\">Happ для macOS</a>.\n"
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

FAQ_ITEMS: dict[str, dict[str, str]] = {
    "what_is_subscription": {
        "title": "Что такое subscription URL?",
        "body": (
            "Это ссылка, через которую клиент забирает актуальный список VPN-конфигов. "
            "Один и тот же URL можно импортировать на несколько устройств."
        ),
    },
    "how_many_devices": {
        "title": "Сколько устройств можно подключить?",
        "body": "Одна подписка действует на три устройства. Если нужно больше, напиши в Поддержку.",
    },
    "vpn_not_working": {
        "title": "VPN не работает",
        "body": (
            "1. Переоткрой доступ в боте.\n"
            "2. Переимпортируй подписку в клиент.\n"
            "3. Проверь дату окончания доступа.\n"
            "4. Если не помогло, напиши в поддержку."
        ),
    },
    "how_to_extend": {
        "title": "Как продлить доступ?",
        "body": "Если подписка оформлена через Tribute, то она продлится автоматически.",
    },
}


def format_expiry(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "не задана"
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    else:
        expires_at = expires_at.astimezone(UTC)
    return expires_at.strftime("%d.%m.%Y %H:%M UTC")


def welcome_text(
    name: str,
    *,
    state: SubscriptionState,
    expires_at: datetime | None,
) -> str:
    if state == "active":
        status_line = "Активна"
        hint_line = "Получить доступ ниже"
    elif state == "inactive":
        status_line = "Закончилась"
        hint_line = "Оплатить ниже"
    else:
        status_line = "Не оформлена"
        hint_line = "Оформить подписку ниже"
    return (
        f"Привет, {name}!\n\n"
        "Izotop Connect — быстрое, стабильное и безопасное подключение к интернету\n\n"
        f"<b>Подписка</b>: {status_line}\n"
        f"<i>{hint_line}</i>"
    )


def keys_text(*, expires_at: datetime | None, subscription_url: str) -> str:
    return (
        "<b>Твой доступ готов</b>\n\n"
        f"<b>Активен до:</b> {format_expiry(expires_at)}\n"
        f"<b>Subscription URL:</b>\n<code>{subscription_url}</code>\n\n"
        "Используй кнопку ниже или QR-код, чтобы импортировать подписку в клиент."
    )


def inactive_access_text(*, state: SubscriptionState) -> str:
    if state == "new":
        return (
            "У тебя пока нет активной подписки.\n\n"
            "Оформи доступ по кнопке ниже. Если оплата уже прошла, немного подожди или напиши в поддержку."
        )
    return (
        "Сейчас твоя подписка неактивна.\n\n"
        "Если доступ уже должен быть активен, напиши в поддержку."
    )


def admin_stats_text(total_users: int, active_subscriptions: int, vpn_accounts: int, webhooks: int) -> str:
    return (
        "<b>Админка Izotop Connect</b>\n\n"
        f"Пользователи: <b>{total_users}</b>\n"
        f"Активные подписки: <b>{active_subscriptions}</b>\n"
        f"VPN-аккаунты: <b>{vpn_accounts}</b>\n"
        f"Webhook events: <b>{webhooks}</b>"
    )


def admin_user_card_text(
    *,
    name: str,
    telegram_user_id: int,
    telegram_username: str | None,
    is_active: bool,
    expires_at: datetime | None,
    has_vpn: bool,
    device_limit: int,
    source: str | None,
    remnawave_username: str | None = None,
) -> str:
    username = f"@{telegram_username}" if telegram_username else "не указан"
    vpn_state = "есть" if has_vpn else "нет"
    status = "активна" if is_active else "неактивна"
    lines = [
        f"<b>{name}</b>",
        "",
        f"<b>Telegram ID:</b> <code>{telegram_user_id}</code>",
        f"<b>Username:</b> {username}",
        f"<b>Подписка:</b> {status}",
        f"<b>Активна до:</b> {format_expiry(expires_at)}",
        f"<b>Лимит устройств:</b> {device_limit}",
        f"<b>VPN-аккаунт:</b> {vpn_state}",
    ]
    if source:
        lines.append(f"<b>Источник:</b> {source}")
    if remnawave_username:
        lines.append(f"<b>Remnawave user:</b> <code>{remnawave_username}</code>")
    return "\n".join(lines)


def admin_users_list_text(rows: Iterable[AdminUserRow], *, title: str) -> str:
    rows = list(rows)
    if not rows:
        return f"<b>{title}</b>\n\nСписок пока пуст."
    lines = [f"<b>{title}</b>", ""]
    for row in rows:
        username = f"@{row.telegram_username}" if row.telegram_username else "без username"
        marker = "ACTIVE" if row.is_active else "INACTIVE"
        vpn = f"VPN:{row.device_limit}" if row.has_vpn else f"noVPN:{row.device_limit}"
        lines.append(
            f"<code>{row.telegram_user_id}</code> | {username} | {marker} | {vpn} | {format_expiry(row.expires_at)}"
        )
    return "\n".join(lines)


def admin_webhooks_text(rows: Iterable[WebhookEventRow]) -> str:
    rows = list(rows)
    if not rows:
        return "<b>Webhook events</b>\n\nСобытий пока нет."
    lines = ["<b>Webhook events</b>", ""]
    for row in rows:
        processed = format_expiry(row.processed_at)
        lines.append(f"{processed} | <b>{row.event_name}</b>\n<code>{row.event_key}</code>")
    return "\n\n".join(lines)


def faq_text(item_key: str | None = None) -> str:
    if item_key is None:
        return (
            "<b>FAQ</b>\n\n"
            "Здесь собраны быстрые ответы по подписке, устройствам и типовым проблемам."
        )
    item = FAQ_ITEMS[item_key]
    return f"<b>{item['title']}</b>\n\n{item['body']}"
