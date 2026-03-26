from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def home_keyboard(*, has_access: bool, is_admin: bool, buy_url: str) -> InlineKeyboardMarkup:
    rows = []
    if has_access:
        rows.append([InlineKeyboardButton(text="Получить доступ", callback_data="home:access")])
        rows.append([InlineKeyboardButton(text="Мои ключи", callback_data="home:keys")])
    else:
        rows.append([InlineKeyboardButton(text="Оформить доступ", url=buy_url)])
        rows.append([InlineKeyboardButton(text="Проверить подписку", callback_data="home:refresh")])
    rows.append([InlineKeyboardButton(text="Инструкции", callback_data="home:guides")])
    rows.append([InlineKeyboardButton(text="Поддержка", callback_data="home:support")])
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админка", callback_data="admin:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_keyboard(*, prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="iPhone", callback_data=f"{prefix}:iphone"),
                InlineKeyboardButton(text="Android", callback_data=f"{prefix}:android"),
            ],
            [
                InlineKeyboardButton(text="Windows", callback_data=f"{prefix}:windows"),
                InlineKeyboardButton(text="macOS", callback_data=f"{prefix}:macos"),
            ],
            [InlineKeyboardButton(text="Smart TV", callback_data=f"{prefix}:smart_tv")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def access_result_keyboard(subscription_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть подписку", url=subscription_url)],
            [InlineKeyboardButton(text="Показать QR", callback_data="key:qr")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def keys_keyboard(subscription_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть подписку", url=subscription_url)],
            [InlineKeyboardButton(text="Показать QR", callback_data="key:qr")],
            [InlineKeyboardButton(text="Обновить", callback_data="home:refresh")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def support_keyboard(*, support_url: str, faq_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать в поддержку", url=support_url)],
            [InlineKeyboardButton(text="FAQ", url=faq_url)],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Найти пользователя", callback_data="admin:find_prompt")],
            [InlineKeyboardButton(text="Импортировать вручную", callback_data="admin:import_prompt")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def admin_user_keyboard(telegram_user_id: int, *, has_access: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Обновить карточку", callback_data=f"admin:view:{telegram_user_id}")],
        [InlineKeyboardButton(text="Синхронизировать VPN", callback_data=f"admin:sync:{telegram_user_id}")],
    ]
    if has_access:
        rows.insert(
            1,
            [InlineKeyboardButton(text="Открыть подписку", callback_data=f"admin:key:{telegram_user_id}")],
        )
    rows.append([InlineKeyboardButton(text="Назад в админку", callback_data="admin:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
