from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import qrcode
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from izotop_connect_bot.bot.keyboards import (
    access_result_keyboard,
    admin_keyboard,
    admin_user_keyboard,
    device_keyboard,
    faq_item_keyboard,
    faq_keyboard,
    home_keyboard,
    keys_keyboard,
    support_keyboard,
)
from izotop_connect_bot.bot.texts import (
    DEVICE_GUIDES,
    FAQ_ITEMS,
    admin_user_card_text,
    admin_stats_text,
    admin_users_list_text,
    admin_webhooks_text,
    faq_text,
    inactive_access_text,
    keys_text,
    welcome_text,
)
from izotop_connect_bot.config import Settings
from izotop_connect_bot.services.access import AccessBundle, AccessService


class AdminStates(StatesGroup):
    waiting_for_lookup = State()
    waiting_for_manual_import = State()


def _display_name(message: Message) -> str:
    return message.from_user.first_name if message.from_user else "друг"


def _is_admin(message: Message | CallbackQuery, settings: Settings) -> bool:
    user = message.from_user
    return bool(user and user.id in settings.bot_admin_ids)


async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup=None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _send_dashboard(message: Message, access: AccessBundle, settings: Settings) -> None:
    name = _display_name(message)
    await message.answer(
        welcome_text(name, is_active=access.is_active, expires_at=access.expires_at),
        reply_markup=home_keyboard(
            has_access=access.is_active,
            is_admin=_is_admin(message, settings),
            buy_url=settings.bot_buy_url,
        ),
    )


def _qr_image(data: str) -> BufferedInputFile:
    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename="subscription.png")


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
        await _safe_edit_text(
            callback.message,
            welcome_text(
                callback.from_user.first_name or "друг",
                is_active=access.is_active,
                expires_at=access.expires_at,
            ),
            reply_markup=home_keyboard(
                has_access=access.is_active,
                is_admin=_is_admin(callback, settings),
                buy_url=settings.bot_buy_url,
            ),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:refresh")
    async def on_refresh(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.refresh_remote_state(callback.from_user.id)
        await _safe_edit_text(
            callback.message,
            welcome_text(
                callback.from_user.first_name or "друг",
                is_active=access.is_active,
                expires_at=access.expires_at,
            ),
            reply_markup=home_keyboard(
                has_access=access.is_active,
                is_admin=_is_admin(callback, settings),
                buy_url=settings.bot_buy_url,
            ),
        )
        await callback.answer("Статус обновлён")

    @router.callback_query(F.data == "home:access")
    async def on_access(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.message:
            return
        access = await access_service.get_access_bundle(callback.from_user.id)
        if not access.is_active:
            await _safe_edit_text(
                callback.message,
                inactive_access_text(),
                reply_markup=home_keyboard(
                    has_access=False,
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                ),
            )
            await callback.answer()
            return
        await _safe_edit_text(
            callback.message,
            "Выбери устройство. Мы дадим короткую инструкцию и твою подписку.",
            reply_markup=device_keyboard(prefix="access"),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:guides")
    async def on_guides(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        await _safe_edit_text(
            callback.message,
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
            await _safe_edit_text(
                callback.message,
                "У тебя пока нет выданного доступа. Нажми <b>Получить доступ</b>, и мы выдадим подписку.",
                reply_markup=home_keyboard(
                    has_access=access.is_active,
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                ),
            )
            await callback.answer()
            return
        await _safe_edit_text(
            callback.message,
            keys_text(
                expires_at=access.expires_at,
                subscription_url=access.vpn_account.subscription_url,
            ),
            reply_markup=keys_keyboard(access.vpn_account.subscription_url),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:support")
    async def on_support(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        await _safe_edit_text(
            callback.message,
            "Если что-то пошло не так, напиши в поддержку. Там же можно уточнить статус оплаты и перенос доступа.",
            reply_markup=support_keyboard(support_url=settings.bot_support_url),
        )
        await callback.answer()

    @router.callback_query(F.data == "home:faq")
    async def on_faq(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        await _safe_edit_text(
            callback.message,
            faq_text(),
            reply_markup=faq_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("faq:"))
    async def on_faq_item(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        _, item_key = callback.data.split(":", 1)
        if item_key not in FAQ_ITEMS:
            await callback.answer("Такого FAQ пока нет", show_alert=True)
            return
        await _safe_edit_text(
            callback.message,
            faq_text(item_key),
            reply_markup=faq_item_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("guide:"))
    async def on_guide(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        _, device = callback.data.split(":", 1)
        guide = DEVICE_GUIDES[device]
        await _safe_edit_text(
            callback.message,
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
            await _safe_edit_text(
                callback.message,
                inactive_access_text(),
                reply_markup=home_keyboard(
                    has_access=False,
                    is_admin=_is_admin(callback, settings),
                    buy_url=settings.bot_buy_url,
                ),
            )
            await callback.answer()
            return

        access = await access_service.get_access_bundle(callback.from_user.id)
        await _safe_edit_text(
            callback.message,
            f"<b>{guide['title']}</b>\n\n{guide['body']}\n\n"
            f"{keys_text(expires_at=access.expires_at, subscription_url=account.subscription_url)}",
            reply_markup=access_result_keyboard(account.subscription_url),
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
        rows = await access_service.admin_list_users(limit=50)
        await _safe_edit_text(
            callback.message,
            admin_users_list_text(rows, title="Все пользователи"),
            reply_markup=admin_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:active")
    async def on_admin_active(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        rows = await access_service.admin_list_users(active_only=True, limit=50)
        await _safe_edit_text(
            callback.message,
            admin_users_list_text(rows, title="Активные пользователи"),
            reply_markup=admin_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:webhooks")
    async def on_admin_webhooks(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        rows = await access_service.admin_list_webhooks(limit=20)
        await _safe_edit_text(
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
        await _safe_edit_text(
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

    @router.callback_query(F.data == "admin:stats")
    async def on_admin_stats(callback: CallbackQuery) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        stats = await access_service.admin_get_stats()
        await _safe_edit_text(
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
        await state.set_state(AdminStates.waiting_for_lookup)
        await callback.message.answer("Пришли <code>telegram_user_id</code>, и я покажу карточку пользователя.")
        await callback.answer()

    @router.callback_query(F.data == "admin:import_prompt")
    async def on_admin_import_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_admin(callback, settings) or not callback.message:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await state.set_state(AdminStates.waiting_for_manual_import)
        await callback.message.answer(
            "Пришли строку в формате:\n"
            "<code>telegram_user_id YYYY-MM-DD [device_limit] [комментарий]</code>\n"
            "или\n"
            "<code>telegram_user_id forever [device_limit] [комментарий]</code>\n\n"
            "Примеры:\n"
            "<code>123456789 2026-05-10 3 tribute_old_user</code>\n"
            "<code>123456789 forever 9 vip_friend</code>"
        )
        await callback.answer()

    @router.message(AdminStates.waiting_for_lookup)
    async def on_admin_lookup(message: Message, state: FSMContext) -> None:
        if not _is_admin(message, settings):
            return
        try:
            telegram_user_id = int((message.text or "").strip())
        except ValueError:
            await message.answer("Нужен числовой <code>telegram_user_id</code>.")
            return
        access = await access_service.admin_find_user(telegram_user_id)
        if access.user is None:
            await message.answer("Пользователь не найден.")
            return
        text = admin_user_card_text(
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
        await message.answer(
            text,
            reply_markup=admin_user_keyboard(
                access.user.telegram_user_id,
                has_access=access.vpn_account is not None,
            ),
        )
        await state.clear()

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
        await _safe_edit_text(
            callback.message,
            admin_user_card_text(
                name=access.user.first_name or access.user.telegram_username or str(access.user.telegram_user_id),
                telegram_user_id=access.user.telegram_user_id,
                telegram_username=access.user.telegram_username,
                is_active=access.is_active,
                expires_at=access.expires_at,
                has_vpn=access.vpn_account is not None,
                device_limit=access.user.device_limit,
                source=access.subscription.source if access.subscription else None,
                remnawave_username=access.vpn_account.remnawave_username if access.vpn_account else None,
            ),
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
        await _safe_edit_text(
            callback.message,
            admin_user_card_text(
                name=refreshed.user.first_name or refreshed.user.telegram_username or str(refreshed.user.telegram_user_id),
                telegram_user_id=refreshed.user.telegram_user_id,
                telegram_username=refreshed.user.telegram_username,
                is_active=refreshed.is_active,
                expires_at=refreshed.expires_at,
                has_vpn=refreshed.vpn_account is not None,
                device_limit=refreshed.user.device_limit,
                source=refreshed.subscription.source if refreshed.subscription else None,
                remnawave_username=refreshed.vpn_account.remnawave_username if refreshed.vpn_account else None,
            ),
            reply_markup=admin_user_keyboard(
                telegram_user_id,
                has_access=refreshed.vpn_account is not None,
            ),
        )
        await callback.answer("VPN синхронизирован")

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
            reply_markup=keys_keyboard(access.vpn_account.subscription_url),
        )
        await callback.answer()

    return router
