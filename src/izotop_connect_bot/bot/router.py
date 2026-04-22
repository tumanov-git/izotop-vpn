from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from html import escape
from io import BytesIO
from pathlib import Path

import qrcode
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, InputMediaPhoto, Message

from izotop_connect_bot.bot.keyboards import (
    access_result_keyboard,
    admin_broadcast_confirm_keyboard,
    admin_broadcast_menu_keyboard,
    admin_cancel_keyboard,
    admin_delete_confirm_keyboard,
    admin_keyboard,
    admin_user_keyboard,
    admin_users_pagination_keyboard,
    device_keyboard,
    faq_item_keyboard,
    faq_keyboard,
    home_keyboard,
    keys_keyboard,
    promo_entry_keyboard,
)
from izotop_connect_bot.bot.texts import (
    DEVICE_GUIDES,
    FAQ_ITEMS,
    SubscriptionState,
    admin_broadcast_confirm_text,
    admin_broadcast_menu_text,
    admin_user_card_text,
    admin_stats_text,
    admin_webhooks_text,
    faq_text,
    inactive_access_text,
    keys_text,
    paginated_admin_users_list_text,
    welcome_text,
)
from izotop_connect_bot.config import Settings
from izotop_connect_bot.links import build_happ_link
from izotop_connect_bot.services.access import AccessBundle, AccessService, normalize_promo_code


class AdminStates(StatesGroup):
    waiting_for_lookup = State()
    waiting_for_manual_import = State()
    waiting_for_extend_access = State()
    waiting_for_device_limit = State()
    waiting_for_promo_code_text = State()
    waiting_for_promo_create_meta = State()
    waiting_for_broadcast_promo_code = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_confirm = State()


class UserStates(StatesGroup):
    waiting_for_promo_code = State()


PICS_DIR = Path(__file__).resolve().parent.parent / "pics"
ADMIN_USERS_PAGE_SIZE = 20
MAX_BROADCAST_TEXT_LENGTH = 4000
STATUS_PICTURES: dict[SubscriptionState, Path] = {
    "new": PICS_DIR / "sub_new.png",
    "active": PICS_DIR / "sub_active.png",
    "inactive": PICS_DIR / "sub_inactive.png",
}


def _display_name(message: Message) -> str:
    return message.from_user.first_name if message.from_user else "друг"


def _is_admin(message: Message | CallbackQuery, settings: Settings) -> bool:
    user = message.from_user
    return bool(user and user.id in settings.bot_admin_ids)


def _subscription_state(access: AccessBundle) -> SubscriptionState:
    if access.subscription is None:
        return "new"
    if access.is_active:
        return "active"
    return "inactive"


def _picture_file(state: SubscriptionState) -> FSInputFile:
    return FSInputFile(str(STATUS_PICTURES[state]))


def _access_url(settings: Settings, subscription_url: str) -> str:
    return build_happ_link(settings.app_base_url, subscription_url)


async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup=None,
) -> None:
    try:
        await message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _safe_edit_caption(
    message: Message,
    caption: str,
    *,
    reply_markup=None,
) -> None:
    try:
        await message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _safe_edit_media(
    message: Message,
    state: SubscriptionState,
    caption: str,
    *,
    reply_markup=None,
) -> None:
    try:
        await message.edit_media(
            media=InputMediaPhoto(
                media=_picture_file(state),
                caption=caption,
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _render_admin_screen(
    message: Message,
    text: str,
    *,
    reply_markup=None,
) -> None:
    if message.photo:
        if len(text) <= 1024:
            await _safe_edit_caption(message, text, reply_markup=reply_markup)
        else:
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
            await message.answer(text, reply_markup=reply_markup)
        return
    await _safe_edit_text(message, text, reply_markup=reply_markup)


def _admin_users_title(*, active_only: bool) -> str:
    return "Активные пользователи" if active_only else "Все пользователи"


def _broadcast_audience_label(*, target: str, promo_code: str | None) -> str:
    if target == "promo" and promo_code:
        preview = promo_code[:10] + "..." if len(promo_code) > 10 else promo_code
        return f"Промокод: <code>{escape(preview)}</code>"
    return "Все пользователи"


async def _render_admin_users_page(
    message: Message,
    access_service: AccessService,
    *,
    active_only: bool,
    offset: int,
) -> None:
    total = await access_service.admin_count_users(active_only=active_only)
    safe_offset = max(0, offset)
    if total > 0 and safe_offset >= total:
        safe_offset = max(total - ADMIN_USERS_PAGE_SIZE, 0)
    rows = await access_service.admin_list_users(
        active_only=active_only,
        limit=ADMIN_USERS_PAGE_SIZE,
        offset=safe_offset,
    )
    await _render_admin_screen(
        message,
        paginated_admin_users_list_text(
            rows,
            title=_admin_users_title(active_only=active_only),
            total=total,
            offset=safe_offset,
            limit=ADMIN_USERS_PAGE_SIZE,
        ),
        reply_markup=admin_users_pagination_keyboard(
            active_only=active_only,
            offset=safe_offset,
            limit=ADMIN_USERS_PAGE_SIZE,
            total=total,
        ),
    )


async def _send_broadcast_message(bot, telegram_user_id: int, text: str) -> bool:
    for _ in range(3):
        try:
            await bot.send_message(telegram_user_id, text)
            return True
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
        except (TelegramBadRequest, TelegramForbiddenError):
            return False
        except Exception:
            return False
    return False


async def _render_user_screen(
    message: Message,
    access: AccessBundle,
    caption: str,
    *,
    reply_markup=None,
    refresh_media: bool = False,
) -> None:
    state = _subscription_state(access)
    if message.photo:
        if refresh_media:
            await _safe_edit_media(
                message,
                state,
                caption,
                reply_markup=reply_markup,
            )
        else:
            await _safe_edit_caption(
                message,
                caption,
                reply_markup=reply_markup,
            )
        return
    await message.answer_photo(
        _picture_file(state),
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def _send_dashboard(message: Message, access: AccessBundle, settings: Settings) -> None:
    name = _display_name(message)
    await _render_user_screen(
        message,
        access,
        welcome_text(
            name,
            state=_subscription_state(access),
            expires_at=access.expires_at,
        ),
        reply_markup=home_keyboard(
            state=_subscription_state(access),
            is_admin=_is_admin(message, settings),
            buy_url=settings.bot_buy_url,
            support_url=settings.bot_support_url,
        ),
        refresh_media=True,
    )


def _qr_image(data: str) -> BufferedInputFile:
    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename="subscription.png")


def _admin_user_text(access: AccessBundle) -> str:
    if access.user is None:
        return "Пользователь не найден."
    return admin_user_card_text(
        name=access.user.first_name or access.user.telegram_username or str(access.user.telegram_user_id),
        telegram_user_id=access.user.telegram_user_id,
        telegram_username=access.user.telegram_username,
        is_active=access.is_active,
        expires_at=access.expires_at,
        has_vpn=access.vpn_account is not None,
        device_limit=access.user.device_limit,
        source=access.subscription.source if access.subscription else None,
        remnawave_username=access.vpn_account.remnawave_username if access.vpn_account else None,
    )


def _split_lookup_value(raw_text: str) -> tuple[str, str] | None:
    parts = raw_text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    lookup, value = parts
    if not lookup or not value:
        return None
    return lookup, value.strip()


def create_router(access_service: AccessService, settings: Settings) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        if not message.from_user:
            return
        await access_service.register_telegram_user(message.from_user)
        access = await access_service.get_access_bundle(message.from_user.id)
        await _send_dashboard(message, access, settings)

    @router.callback_query(F.data == "home:root")
    async def on_home_root(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            welcome_text(
                callback.from_user.first_name or "друг",
                state=_subscription_state(access),
                expires_at=access.expires_at,
            ),
            reply_markup=home_keyboard(
                state=_subscription_state(access),
                is_admin=_is_admin(callback, settings),
                buy_url=settings.bot_buy_url,
                support_url=settings.bot_support_url,
            ),
            refresh_media=True,
        )
        await callback.answer()

    @router.callback_query(F.data == "home:refresh")
    async def on_refresh(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.refresh_remote_state(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            welcome_text(
                callback.from_user.first_name or "друг",
                state=_subscription_state(access),
                expires_at=access.expires_at,
            ),
            reply_markup=home_keyboard(
                state=_subscription_state(access),
                is_admin=_is_admin(callback, settings),
                buy_url=settings.bot_buy_url,
                support_url=settings.bot_support_url,
            ),
            refresh_media=True,
        )
        await callback.answer("Статус обновлён")

    @router.callback_query(F.data == "home:promo")
    async def on_promo_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        if _subscription_state(access) == "active":
            await callback.answer("Промокод сейчас не нужен", show_alert=True)
            return
        await state.set_state(UserStates.waiting_for_promo_code)
        await _render_user_screen(
            callback.message,
            access,
            "Введи промокод, который у тебя есть",
            reply_markup=promo_entry_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:access")
    async def on_access(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        if not access.is_active:
            await _render_user_screen(
                callback.message,
                access,
                inactive_access_text(state=_subscription_state(access)),
                reply_markup=home_keyboard(
                    state=_subscription_state(access),
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                    support_url=settings.bot_support_url,
                ),
            )
            await callback.answer()
            return
        await _render_user_screen(
            callback.message,
            access,
            "Выбери устройство. Мы дадим короткую инструкцию и твой доступ.",
            reply_markup=device_keyboard(prefix="access"),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:guides")
    async def on_guides(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            "Выбери устройство, для которого показать краткий гайд.",
            reply_markup=device_keyboard(prefix="guide"),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:keys")
    async def on_keys(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        if not access.vpn_account:
            await _render_user_screen(
                callback.message,
                access,
                "У тебя пока нет выданного доступа. Нажми <b>Получить доступ</b>, и мы выдадим подписку.",
                reply_markup=home_keyboard(
                    state=_subscription_state(access),
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                    support_url=settings.bot_support_url,
                ),
            )
            await callback.answer()
            return
        await _render_user_screen(
            callback.message,
            access,
            keys_text(
                expires_at=access.expires_at,
                subscription_url=access.vpn_account.subscription_url,
            ),
            reply_markup=keys_keyboard(_access_url(settings, access.vpn_account.subscription_url)),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:faq")
    async def on_faq(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            faq_text(),
            reply_markup=faq_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("faq:"))
    async def on_faq_item(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        _, item_key = callback.data.split(":", 1)
        if item_key not in FAQ_ITEMS:
            await callback.answer("Такого FAQ пока нет", show_alert=True)
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            faq_text(item_key),
            reply_markup=faq_item_keyboard(support_url=settings.bot_support_url),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("guide:"))
    async def on_guide(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        _, device = callback.data.split(":", 1)
        guide = DEVICE_GUIDES[device]
        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            f"<b>{guide['title']}</b>\n\n{guide['body']}",
            reply_markup=device_keyboard(prefix="access"),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("access:"))
    async def on_access_device(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        _, device = callback.data.split(":", 1)
        guide = DEVICE_GUIDES[device]
        try:
            account = await access_service.ensure_vpn_access(
                telegram_user_id=callback.from_user.id,
                telegram_username=callback.from_user.username,
                first_name=callback.from_user.first_name,
            )
        except PermissionError:
            access = await access_service.get_access_bundle(callback.from_user.id)
            await _render_user_screen(
                callback.message,
                access,
                inactive_access_text(state=_subscription_state(access)),
                reply_markup=home_keyboard(
                    state=_subscription_state(access),
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                    support_url=settings.bot_support_url,
                ),
            )
            await callback.answer()
            return

        access = await access_service.get_access_bundle(callback.from_user.id)
        await _render_user_screen(
            callback.message,
            access,
            f"<b>{guide['title']}</b>\n\n{guide['body']}\n\n"
            f"{keys_text(expires_at=access.expires_at, subscription_url=account.subscription_url)}",
            reply_markup=access_result_keyboard(_access_url(settings, account.subscription_url)),
            refresh_media=True,
        )
        await callback.answer("Подписка готова")

    @router.callback_query(F.data == "key:qr")
    async def on_key_qr(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        if not access.vpn_account:
            await callback.answer("Сначала нужно выдать доступ", show_alert=True)
            return
        await callback.message.answer_photo(
            _qr_image(access.vpn_account.subscription_url),
            caption="QR для импорта подписки в совместимый клиент.",
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:users")
    async def on_admin_users(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await _render_admin_users_page(
            callback.message,
            access_service,
            active_only=False,
            offset=0,
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:active")
    async def on_admin_active(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await _render_admin_users_page(
            callback.message,
            access_service,
            active_only=True,
            offset=0,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:list:"))
    async def on_admin_users_page(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _, _, mode, raw_offset = callback.data.split(":")
        await _render_admin_users_page(
            callback.message,
            access_service,
            active_only=mode == "active",
            offset=int(raw_offset),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:broadcast_menu")
    async def on_admin_broadcast_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await _render_admin_screen(
            callback.message,
            admin_broadcast_menu_text(),
            reply_markup=admin_broadcast_menu_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:broadcast:all")
    async def on_admin_broadcast_all(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        recipients_count = await access_service.admin_count_users()
        await state.clear()
        await state.update_data(
            broadcast_target="all",
            broadcast_promo_code=None,
            broadcast_recipients_count=recipients_count,
        )
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await _render_admin_screen(
            callback.message,
            "Пришли текст рассылки одним сообщением.\n\n"
            f"Сейчас в выборке: <b>{recipients_count}</b> пользователей.\n"
            "Сообщение уйдёт как обычный текст без HTML-разметки.",
            reply_markup=admin_cancel_keyboard("admin:broadcast_menu"),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:broadcast:promo")
    async def on_admin_broadcast_promo(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_broadcast_promo_code)
        await _render_admin_screen(
            callback.message,
            "Пришли промокод целиком отдельным сообщением.\n"
            "Я найду всех пользователей, которые его активировали.",
            reply_markup=admin_cancel_keyboard("admin:broadcast_menu"),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:webhooks")
    async def on_admin_webhooks(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        rows = await access_service.admin_list_webhooks(limit=20)
        await _render_admin_screen(
            callback.message,
            admin_webhooks_text(rows),
            reply_markup=admin_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:menu")
    async def on_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        stats = await access_service.admin_get_stats()
        await _render_admin_screen(
            callback.message,
            admin_stats_text(
                stats.total_users,
                stats.active_subscriptions,
                stats.vpn_accounts,
                stats.processed_webhooks,
            ),
            reply_markup=admin_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:find_prompt")
    async def on_admin_find_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_lookup)
        await _render_admin_screen(
            callback.message,
            "Пришли <code>telegram_user_id</code> или <code>@username</code>, и я покажу карточку пользователя.",
            reply_markup=admin_cancel_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:import_prompt")
    async def on_admin_import_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_manual_import)
        await _render_admin_screen(
            callback.message,
            "Пришли строку в формате:\n"
            "<code>telegram_user_id YYYY-MM-DD [device_limit] [комментарий]</code>\n"
            "или\n"
            "<code>telegram_user_id forever [device_limit] [комментарий]</code>\n\n"
            "Примеры:\n"
            "<code>123456789 2026-05-10 3 tribute_old_user</code>\n"
            "<code>123456789 forever 9 vip_friend</code>",
            reply_markup=admin_cancel_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:extend_prompt")
    async def on_admin_extend_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_extend_access)
        await _render_admin_screen(
            callback.message,
            "Пришли строку в формате:\n"
            "<code>telegram_user_id дни</code>\n"
            "или\n"
            "<code>@username дни</code>\n\n"
            "Примеры:\n"
            "<code>123456789 30</code>\n"
            "<code>@some_user 14</code>",
            reply_markup=admin_cancel_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:device_prompt")
    async def on_admin_device_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_device_limit)
        await _render_admin_screen(
            callback.message,
            "Пришли строку в формате:\n"
            "<code>telegram_user_id лимит</code>\n"
            "или\n"
            "<code>@username лимит</code>\n\n"
            "Примеры:\n"
            "<code>123456789 5</code>\n"
            "<code>@some_user 7</code>",
            reply_markup=admin_cancel_keyboard(),
        )
        await callback.answer()

    @router.message(AdminStates.waiting_for_lookup)
    async def on_admin_lookup(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        lookup = (message.text or "").strip()
        if not lookup:
            await message.answer("Нужен <code>telegram_user_id</code> или <code>@username</code>.")
            return
        access = await access_service.admin_find_user_by_lookup(lookup)
        if access.user is None:
            await message.answer("Пользователь не найден.")
            return
        await message.answer(
            _admin_user_text(access),
            reply_markup=admin_user_keyboard(
                access.user.telegram_user_id,
                has_access=access.vpn_account is not None,
            ),
        )
        await state.clear()

    @router.message(AdminStates.waiting_for_extend_access)
    async def on_admin_extend_access(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        parsed = _split_lookup_value(message.text or "")
        if parsed is None:
            await message.answer(
                "Нужен формат: <code>telegram_user_id дни</code> или <code>@username дни</code>."
            )
            return
        lookup, raw_days = parsed
        try:
            days = int(raw_days)
        except ValueError:
            await message.answer("Количество дней должно быть целым числом.")
            return
        if days <= 0:
            await message.answer("Количество дней должно быть больше нуля.")
            return
        access = await access_service.admin_extend_access(lookup=lookup, days=days)
        if access is None or access.user is None:
            await message.answer("Пользователь не найден.")
            return
        await message.answer(
            f"Подписка продлена на <b>{days}</b> дн.\n\n{_admin_user_text(access)}",
            reply_markup=admin_user_keyboard(
                access.user.telegram_user_id,
                has_access=access.vpn_account is not None,
            ),
        )
        await state.clear()

    @router.message(AdminStates.waiting_for_device_limit)
    async def on_admin_device_limit(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        parsed = _split_lookup_value(message.text or "")
        if parsed is None:
            await message.answer(
                "Нужен формат: <code>telegram_user_id лимит</code> или <code>@username лимит</code>."
            )
            return
        lookup, raw_limit = parsed
        try:
            device_limit = int(raw_limit)
        except ValueError:
            await message.answer("Лимит устройств должен быть целым числом.")
            return
        if device_limit <= 0:
            await message.answer("Лимит устройств должен быть больше нуля.")
            return
        access = await access_service.admin_update_device_limit(
            lookup=lookup,
            device_limit=device_limit,
        )
        if access is None or access.user is None:
            await message.answer("Пользователь не найден.")
            return
        await message.answer(
            f"Лимит устройств обновлён до <b>{device_limit}</b>.\n\n{_admin_user_text(access)}",
            reply_markup=admin_user_keyboard(
                access.user.telegram_user_id,
                has_access=access.vpn_account is not None,
            ),
        )
        await state.clear()

    @router.message(AdminStates.waiting_for_broadcast_promo_code)
    async def on_admin_broadcast_promo_code(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        raw_code = message.text or ""
        normalized_code = normalize_promo_code(raw_code)
        if not normalized_code:
            await message.answer("Промокод не должен быть пустым.")
            return
        recipients_count = await access_service.admin_count_promo_redemptions(code=normalized_code)
        if recipients_count <= 0:
            await message.answer(
                "По этому промокоду пока нет активировавших пользователей.\n"
                "Пришли другой код или нажми Отмена."
            )
            return
        await state.update_data(
            broadcast_target="promo",
            broadcast_promo_code=normalized_code,
            broadcast_recipients_count=recipients_count,
        )
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await message.answer(
            "Аудитория собрана.\n\n"
            f"<b>Промокод:</b> <code>{escape(normalized_code[:10] + '...' if len(normalized_code) > 10 else normalized_code)}</code>\n"
            f"<b>Получателей:</b> {recipients_count}\n\n"
            "Теперь пришли текст рассылки одним сообщением.\n"
            "Сообщение уйдёт как обычный текст без HTML-разметки.",
            reply_markup=admin_cancel_keyboard("admin:broadcast_menu"),
        )

    @router.message(AdminStates.waiting_for_broadcast_text)
    async def on_admin_broadcast_text(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Текст рассылки не должен быть пустым.")
            return
        if len(text) > MAX_BROADCAST_TEXT_LENGTH:
            await message.answer(
                "Текст слишком длинный для Telegram.\n"
                f"Максимум: {MAX_BROADCAST_TEXT_LENGTH} символов."
            )
            return
        data = await state.get_data()
        target = data.get("broadcast_target", "all")
        promo_code = data.get("broadcast_promo_code")
        recipients_count = int(data.get("broadcast_recipients_count", 0))
        await state.update_data(broadcast_text=text)
        await state.set_state(AdminStates.waiting_for_broadcast_confirm)
        await message.answer(
            admin_broadcast_confirm_text(
                audience_label=_broadcast_audience_label(target=target, promo_code=promo_code),
                recipients_count=recipients_count,
                message_text=text,
            ),
            reply_markup=admin_broadcast_confirm_keyboard(),
        )

    @router.callback_query(F.data == "admin:broadcast:send")
    async def on_admin_broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        data = await state.get_data()
        text = data.get("broadcast_text")
        if not text:
            await callback.answer("Сначала пришли текст рассылки", show_alert=True)
            return
        target = data.get("broadcast_target", "all")
        promo_code = data.get("broadcast_promo_code")
        recipient_ids = await access_service.admin_list_broadcast_user_ids(
            code=promo_code if target == "promo" else None
        )
        recipient_ids = list(dict.fromkeys(recipient_ids))
        if not recipient_ids:
            await state.clear()
            await callback.answer("Получатели не найдены", show_alert=True)
            await _render_admin_screen(
                callback.message,
                admin_broadcast_menu_text(),
                reply_markup=admin_broadcast_menu_keyboard(),
            )
            return
        await callback.answer("Рассылка запущена")
        await _render_admin_screen(
            callback.message,
            "Рассылка выполняется.\n\nЭто может занять немного времени.",
        )
        delivered = 0
        failed = 0
        for telegram_user_id in recipient_ids:
            if await _send_broadcast_message(callback.bot, telegram_user_id, text):
                delivered += 1
            else:
                failed += 1
        audience_label = _broadcast_audience_label(target=target, promo_code=promo_code)
        await _render_admin_screen(
            callback.message,
            "<b>Рассылка завершена</b>\n\n"
            f"<b>Аудитория:</b> {audience_label}\n"
            f"<b>Всего в выборке:</b> {len(recipient_ids)}\n"
            f"<b>Доставлено:</b> {delivered}\n"
            f"<b>Не доставлено:</b> {failed}",
            reply_markup=admin_broadcast_menu_keyboard(),
        )
        await state.clear()

    @router.callback_query(F.data == "admin:broadcast:cancel")
    async def on_admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await _render_admin_screen(
            callback.message,
            admin_broadcast_menu_text(),
            reply_markup=admin_broadcast_menu_keyboard(),
        )
        await callback.answer("Рассылка отменена")

    @router.message(UserStates.waiting_for_promo_code)
    async def on_user_promo_code(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        code = (message.text or "").strip()
        if not code:
            await message.answer("Введи промокод текстом.")
            return
        access = await access_service.redeem_promo_code(
            telegram_user_id=message.from_user.id,
            telegram_username=message.from_user.username,
            first_name=message.from_user.first_name,
            language_code=message.from_user.language_code,
            code=code,
        )
        if access is None:
            await message.answer("Промокод неверный.")
            return
        await state.clear()
        await _send_dashboard(message, access, settings)

    @router.message(AdminStates.waiting_for_manual_import)
    async def on_admin_manual_import(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 2:
            await message.answer(
                "Нужен формат: <code>telegram_user_id YYYY-MM-DD [device_limit] [комментарий]</code> "
                "или <code>telegram_user_id forever [device_limit] [комментарий]</code>."
            )
            return
        try:
            telegram_user_id = int(parts[0])
            raw_expiry = parts[1].strip().lower()
            if raw_expiry == "forever":
                expires_at = datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)
            else:
                parsed = datetime.fromisoformat(parts[1])
                expires_at = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            await message.answer("Не смог разобрать <code>telegram_user_id</code> или дату.")
            return
        device_limit = settings.remnawave_default_device_limit
        note = None
        if len(parts) > 2:
            tail = parts[2].split(maxsplit=1)
            if tail[0].isdigit():
                device_limit = int(tail[0])
                note = tail[1] if len(tail) > 1 else None
            else:
                note = parts[2]
        access = await access_service.admin_manual_import(
            telegram_user_id=telegram_user_id,
            expires_at=expires_at,
            device_limit=device_limit,
            note=note,
            imported_by_admin=message.from_user.id if message.from_user else 0,
        )
        await message.answer(
            "Импорт выполнен.\n\n"
            + admin_user_card_text(
                name=str(telegram_user_id),
                telegram_user_id=telegram_user_id,
                telegram_username=access.user.telegram_username if access.user else None,
                is_active=access.is_active,
                expires_at=access.expires_at,
                has_vpn=access.vpn_account is not None,
                device_limit=access.user.device_limit if access.user else settings.remnawave_default_device_limit,
                source=access.subscription.source if access.subscription else None,
                remnawave_username=access.vpn_account.remnawave_username if access.vpn_account else None,
            ),
            reply_markup=admin_user_keyboard(telegram_user_id, has_access=access.vpn_account is not None),
        )
        await state.clear()

    @router.callback_query(F.data == "admin:promo_prompt")
    async def on_admin_promo_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_for_promo_code_text)
        await _render_admin_screen(
            callback.message,
            "Сначала пришли сам промокод целиком отдельным сообщением.\n"
            "Он может быть длинным и многострочным.",
            reply_markup=admin_cancel_keyboard(),
        )
        await callback.answer()

    @router.message(AdminStates.waiting_for_promo_code_text)
    async def on_admin_promo_code_text(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        raw_code = message.text or ""
        if not normalize_promo_code(raw_code):
            await message.answer("Промокод не должен быть пустым. Пришли текст промокода ещё раз.")
            return
        await state.update_data(promo_code=raw_code)
        await state.set_state(AdminStates.waiting_for_promo_create_meta)
        await message.answer(
            "Теперь пришли вторым сообщением:\n"
            "<code>Дни Кол-во_юзеров</code>\n\n"
            "Пример:\n"
            "<code>7 30</code>"
        )

    @router.message(AdminStates.waiting_for_promo_create_meta)
    async def on_admin_promo_create_meta(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer(
                "Нужен формат: <code>Дни Кол-во_юзеров</code>.\n"
                "Пример: <code>7 30</code>"
            )
            return
        raw_duration, raw_usages = parts
        try:
            duration_days = int(raw_duration)
            max_usages = int(raw_usages)
        except ValueError:
            await message.answer("Длительность и количество использований должны быть числами.")
            return
        if duration_days <= 0 or max_usages <= 0:
            await message.answer("Длительность и количество использований должны быть больше нуля.")
            return
        data = await state.get_data()
        code = data.get("promo_code", "")
        created = await access_service.admin_create_promo_code(
            code=code,
            duration_days=duration_days,
            max_usages=max_usages,
        )
        if not created:
            await state.clear()
            await state.set_state(AdminStates.waiting_for_promo_code_text)
            await message.answer(
                "Такой промокод уже существует или невалиден.\n"
                "Пришли новый текст промокода отдельным сообщением."
            )
            return
        await message.answer(
            "Промокод создан.\n\n"
            f"<b>Символов в коде:</b> {len(normalize_promo_code(code))}\n"
            f"<b>Длительность:</b> {duration_days} дн.\n"
            f"<b>Использований:</b> {max_usages}\n"
            "<b>Устройств:</b> 1"
        )
        await state.clear()

    @router.callback_query(F.data.startswith("admin:view:"))
    async def on_admin_view_user(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        telegram_user_id = int(callback.data.split(":")[-1])
        access = await access_service.admin_find_user(telegram_user_id)
        if access.user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        await _render_admin_screen(
            callback.message,
            _admin_user_text(access),
            reply_markup=admin_user_keyboard(telegram_user_id, has_access=access.vpn_account is not None),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:sync:"))
    async def on_admin_sync_user(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        telegram_user_id = int(callback.data.split(":")[-1])
        access = await access_service.admin_find_user(telegram_user_id)
        if access.user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        if not access.is_active:
            await callback.answer("У пользователя нет активной подписки", show_alert=True)
            return
        await access_service.ensure_vpn_access(
            telegram_user_id=telegram_user_id,
            telegram_username=access.user.telegram_username,
            first_name=access.user.first_name,
        )
        refreshed = await access_service.admin_find_user(telegram_user_id)
        await _render_admin_screen(
            callback.message,
            _admin_user_text(refreshed),
            reply_markup=admin_user_keyboard(
                telegram_user_id,
                has_access=refreshed.vpn_account is not None,
            ),
        )
        await callback.answer("VPN синхронизирован")

    @router.callback_query(F.data.startswith("admin:delete_prompt:"))
    async def on_admin_delete_prompt(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        telegram_user_id = int(callback.data.split(":")[-1])
        access = await access_service.admin_find_user(telegram_user_id)
        if access.user is None and access.subscription is None and access.vpn_account is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        await _render_admin_screen(
            callback.message,
            "Удалить пользователя из базы и отключить его доступ?\n\n"
            f"<b>Telegram ID:</b> <code>{telegram_user_id}</code>",
            reply_markup=admin_delete_confirm_keyboard(telegram_user_id),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:delete:"))
    async def on_admin_delete(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        telegram_user_id = int(callback.data.split(":")[-1])
        deleted = await access_service.admin_delete_user(telegram_user_id)
        if not deleted:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        stats = await access_service.admin_get_stats()
        await _render_admin_screen(
            callback.message,
            admin_stats_text(
                stats.total_users,
                stats.active_subscriptions,
                stats.vpn_accounts,
                stats.processed_webhooks,
            ),
            reply_markup=admin_keyboard(),
        )
        await callback.answer("Пользователь удалён")

    @router.callback_query(F.data.startswith("admin:key:"))
    async def on_admin_key(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings):
            await callback.answer("Нет доступа", show_alert=True)
            return
        telegram_user_id = int(callback.data.split(":")[-1])
        access = await access_service.admin_find_user(telegram_user_id)
        if access.vpn_account is None:
            await callback.answer("У пользователя ещё нет VPN-аккаунта", show_alert=True)
            return
        await callback.message.answer(
            keys_text(
                expires_at=access.expires_at,
                subscription_url=access.vpn_account.subscription_url,
            ),
            reply_markup=keys_keyboard(_access_url(settings, access.vpn_account.subscription_url)),
        )
        await callback.answer()

    return router
