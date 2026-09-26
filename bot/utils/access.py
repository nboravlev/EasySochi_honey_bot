"""Проверка прав на действия менеджера.

Менеджер — пользователь из MANAGER_LIST или OWNER_ID.
Сотрудник админ-чата — любой участник чата ADMIN_CHAT_ID (кнопки заказов
приходят туда) либо менеджер.
"""
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import get_settings
from utils.logging_config import structured_logger

DENIED_TEXT = "🚫 Недостаточно прав для этого действия."


def is_owner(tg_user_id: int | None) -> bool:
    owner_id = get_settings().owner_id
    return owner_id is not None and tg_user_id == owner_id


def is_manager(tg_user_id: int | None) -> bool:
    return tg_user_id in get_settings().manager_ids


def is_staff(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user and is_manager(user.id):
        return True
    return chat is not None and chat.id == get_settings().admin_chat_id


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
        await update.effective_message.reply_text(DENIED_TEXT)
    return ConversationHandler.END


def manager_only(func):
    """Хендлер доступен только менеджерам (MANAGER_LIST/OWNER_ID)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not is_manager(update.effective_user.id if update.effective_user else None):
            return await _deny(update, func.__name__)
        return await func(update, context, *args, **kwargs)
    return wrapper


def staff_only(func):
    """Хендлер доступен менеджерам и участникам админ-чата."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not is_staff(update):
            return await _deny(update, func.__name__)
        return await func(update, context, *args, **kwargs)
    return wrapper
