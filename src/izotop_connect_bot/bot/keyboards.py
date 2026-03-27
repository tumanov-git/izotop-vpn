from __future__ import annotations

from aiogram.enums.button_style import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from izotop_connect_bot.bot.texts import SubscriptionState


def home_keyboard(
    *,
    state: SubscriptionState,
    is_admin: bool,
    buy_url: str,
    support_url: str,
) -> InlineKeyboardMarkup:
    rows = []
    if state == "active":
        rows.append(
            [
                InlineKeyboardButton(
                    text="Получить доступ",
                    callback_data="home:access",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Оформить подписку" if state == "new" else "Оплатить подписку",
                    url=buy_url,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Я оплатил",
                    callback_data="home:refresh",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="FAQ", callback_data="home:faq"),
            InlineKeyboardButton(text="Поддержка", url=support_url),
        ]
    )
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админка", callback_data="admin:menu", style=ButtonStyle.PRIMARY)])
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
            [InlineKeyboardButton(text="Открыть доступ", url=subscription_url, style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="Показать QR", callback_data="key:qr", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def keys_keyboard(subscription_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть доступ", url=subscription_url, style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="Показать QR", callback_data="key:qr", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="Обновить", callback_data="home:refresh")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def faq_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="VPN не работает", callback_data="faq:vpn_not_working", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="Что такое subscription URL?", callback_data="faq:what_is_subscription")],
            [InlineKeyboardButton(text="Сколько устройств можно подключить?", callback_data="faq:how_many_devices")],
            [InlineKeyboardButton(text="Как продлить доступ?", callback_data="faq:how_to_extend")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def faq_item_keyboard(*, support_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Поддержка", url=support_url, style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="Назад", callback_data="home:faq"),
            ],
        ]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Все пользователи", callback_data="admin:users", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="Активные", callback_data="admin:active")],
            [InlineKeyboardButton(text="Webhook events", callback_data="admin:webhooks")],
            [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Найти пользователя", callback_data="admin:find_prompt")],
            [InlineKeyboardButton(text="Импортировать вручную", callback_data="admin:import_prompt")],
            [InlineKeyboardButton(text="Назад", callback_data="home:root")],
        ]
    )


def admin_user_keyboard(telegram_user_id: int, *, has_access: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Обновить карточку",
                callback_data=f"admin:view:{telegram_user_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Синхронизировать VPN",
                callback_data=f"admin:sync:{telegram_user_id}",
                style=ButtonStyle.SUCCESS,
            )
        ],
    ]
    if has_access:
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    text="Открыть доступ",
                    callback_data=f"admin:key:{telegram_user_id}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Удалить пользователя",
                callback_data=f"admin:delete_prompt:{telegram_user_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="Назад в админку", callback_data="admin:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_delete_confirm_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить пользователя",
                    callback_data=f"admin:delete:{telegram_user_id}",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data=f"admin:view:{telegram_user_id}")],
        ]
    )
