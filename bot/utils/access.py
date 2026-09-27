"""Проверка прав.

- Владелец — OWNER_ID из .env (корень доверия, назначает менеджеров).
- Менеджер — users.role_id = MANAGER (назначает владелец командой /managers) или владелец.
- Сотрудник админ-чата — любой участник чата ADMIN_CHAT_ID (туда приходят кнопки заказов) либо менеджер.
"""
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import get_settings
from domain.enums import Role
from services.users import get_role
from utils.logging_config import structured_logger

DENIED_TEXT = "🚫 Недостаточно прав для этого действия."


def is_owner(tg_user_id: int | None) -> bool:
    owner_id = get_settings().owner_id
    return owner_id is not None and tg_user_id == owner_id


async def is_manager(tg_user_id: int | None) -> bool:
    if tg_user_id is None:
        return False
    if is_owner(tg_user_id):
        return True
    return await get_role(tg_user_id) == Role.MANAGER


async def is_staff(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if chat is not None and chat.id == get_settings().admin_chat_id:
        return True
    return bool(user) and await is_manager(user.id)


async def _deny(update: Update, handler_name: str):
    user_id = update.effective_user.id if update.effective_user else None
    structured_logger.warning(
        "Access denied",
        user_id=user_id,
        action="access_denied",
        context={
            "handler": handler_name,
            "chat_id": update.effective_chat.id if update.effective_chat else None,
            "callback_data": update.callback_query.data if update.callback_query else None,
        },
    )
    if update.callback_query:
        await update.callback_query.answer(DENIED_TEXT, show_alert=True)
    elif update.effective_message:
        await update.effective_chat.send_message(DENIED_TEXT)
    return ConversationHandler.END


def _guard(check):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not await check(update):
                return await _deny(update, func.__name__)
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


async def _owner_check(update: Update) -> bool:
    return is_owner(update.effective_user.id if update.effective_user else None)


async def _manager_check(update: Update) -> bool:
    return await is_manager(update.effective_user.id if update.effective_user else None)


owner_only = _guard(_owner_check)
owner_only.__doc__ = "Хендлер доступен только владельцу (OWNER_ID)."
manager_only = _guard(_manager_check)
manager_only.__doc__ = "Хендлер доступен менеджерам и владельцу."
staff_only = _guard(is_staff)
staff_only.__doc__ = "Хендлер доступен менеджерам и участникам админ-чата."
