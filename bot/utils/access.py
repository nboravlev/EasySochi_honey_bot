"""Проверка прав на действия менеджера.

Менеджер — пользователь из MANAGER_LIST или OWNER_ID.
Сотрудник админ-чата — любой участник чата ADMIN_CHAT_ID (кнопки заказов
приходят туда) либо менеджер.
"""
import os
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from utils.logging_config import structured_logger


def _parse_ids(raw: str) -> set[int]:
    return {int(part.strip(" []")) for part in raw.split(",") if part.strip(" []")}


OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
MANAGER_IDS = _parse_ids(os.getenv("MANAGER_LIST", "")) | ({OWNER_ID} if OWNER_ID else set())
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)

DENIED_TEXT = "🚫 Недостаточно прав для этого действия."


def is_owner(tg_user_id: int | None) -> bool:
    return bool(OWNER_ID) and tg_user_id == OWNER_ID


def is_manager(tg_user_id: int | None) -> bool:
    return tg_user_id in MANAGER_IDS


def is_staff(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user and is_manager(user.id):
        return True
    return bool(ADMIN_CHAT_ID) and chat is not None and chat.id == ADMIN_CHAT_ID


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
