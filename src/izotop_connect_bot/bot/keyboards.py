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
    show_white_internet: bool = False,
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
        if show_white_internet:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="Белый интернет",
                        callback_data="home:white",
                        style=ButtonStyle.PRIMARY,
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
                    text="Я оплатил(а)",
                    callback_data="home:refresh",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        )
        rows.append([InlineKeyboardButton(text="Промокод", callback_data="home:promo")])
    rows.append(
        [
            InlineKeyboardButton(text="FAQ", callback_data="home:faq"),
            InlineKeyboardButton(text="Поддержка", url=support_url),
        ]
    )
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админка", callback_data="admin:menu", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def white_internet_keyboard(
    *,
    url_50gb: str | None,
    url_100gb: str | None,
    url_250gb: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    first_row: list[InlineKeyboardButton] = []
    if url_50gb:
        first_row.append(InlineKeyboardButton(text="50 GB · 110 ₽", url=url_50gb, style=ButtonStyle.PRIMARY))
    if url_100gb:
        first_row.append(InlineKeyboardButton(text="100 GB · 220 ₽", url=url_100gb, style=ButtonStyle.PRIMARY))
    if first_row:
        rows.append(first_row)
    if url_250gb:
        rows.append([InlineKeyboardButton(text="250 GB · 550 ₽", url=url_250gb, style=ButtonStyle.PRIMARY)])
    rows.append(
        [
            InlineKeyboardButton(
                text="Получить доступ",
                callback_data="white:access",
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="home:root")])
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


def white_access_result_keyboard(subscription_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть доступ", url=subscription_url, style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="Назад", callback_data="home:white")],
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


def promo_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
            [InlineKeyboardButton(text="Обновить white всем", callback_data="admin:white_sync_all")],
            [InlineKeyboardButton(text="Начислить white GB", callback_data="admin:white_topup_prompt")],
            [InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast_menu")],
            [InlineKeyboardButton(text="Webhook events", callback_data="admin:webhooks")],
            [InlineKeyboardButton(text="Продлить доступ", callback_data="admin:extend_prompt")],
            [InlineKeyboardButton(text="Поднять число девайсов", callback_data="admin:device_prompt")],
            [InlineKeyboardButton(text="Найти пользователя", callback_data="admin:find_prompt")],
            [InlineKeyboardButton(text="Импортировать вручную", callback_data="admin:import_prompt")],
            [InlineKeyboardButton(text="Создать промокод", callback_data="admin:promo_prompt")],
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


def admin_users_pagination_keyboard(
    *,
    active_only: bool,
    offset: int,
    limit: int,
    total: int,
) -> InlineKeyboardMarkup:
    mode = "active" if active_only else "all"
    all_button = (
        InlineKeyboardButton(text="Все", callback_data="admin:list:all:0")
        if active_only
        else InlineKeyboardButton(
            text="Все пользователи",
            callback_data="admin:list:all:0",
            style=ButtonStyle.PRIMARY,
        )
    )
    active_button = (
        InlineKeyboardButton(
            text="Активные",
            callback_data="admin:list:active:0",
            style=ButtonStyle.PRIMARY,
        )
        if active_only
        else InlineKeyboardButton(text="Активные", callback_data="admin:list:active:0")
    )
    rows: list[list[InlineKeyboardButton]] = [
        [all_button, active_button]
    ]
    nav_row: list[InlineKeyboardButton] = []
    if offset > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="Назад",
                callback_data=f"admin:list:{mode}:{max(offset - limit, 0)}",
            )
        )
    if offset + limit < total:
        nav_row.append(
            InlineKeyboardButton(
                text="Дальше",
                callback_data=f"admin:list:{mode}:{offset + limit}",
            )
        )
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="Назад в админку", callback_data="admin:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Всем пользователям",
                    callback_data="admin:broadcast:all",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="По промокоду",
                    callback_data="admin:broadcast:promo",
                )
            ],
            [InlineKeyboardButton(text="Назад в админку", callback_data="admin:menu")],
        ]
    )


def admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отправить",
                    callback_data="admin:broadcast:send",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data="admin:broadcast:cancel",
                )
            ],
            [InlineKeyboardButton(text="Назад к рассылке", callback_data="admin:broadcast_menu")],
        ]
    )


def admin_cancel_keyboard(callback_data: str = "admin:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=callback_data)],
        ]
    )
