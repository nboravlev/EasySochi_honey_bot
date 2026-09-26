from telegram import Update
from telegram.ext import (
    ConversationHandler, ContextTypes
)

from utils.access import staff_only
from config import get_settings

ADMIN_CHAT_ID = get_settings().admin_chat_id
REPLY_WAITING = 1


@staff_only
async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, user_id_str = query.data.split("_")
    target_user_id = int(user_id_str)

    # сохраняем target_user_id в context.user_data админа
    context.user_data["reply_to_user"] = target_user_id

    await query.message.reply_text(
        f"✍️ Введите сообщение для пользователя {target_user_id}:"
    )

    return REPLY_WAITING


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_user_id = context.user_data.get("reply_to_user")
    if not target_user_id:
        await update.message.reply_text("❌ Ошибка: нет пользователя для ответа.")
        return ConversationHandler.END

    reply_text = update.message.text.strip()

    # Отправляем пользователю
    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"📩 Ответ администратора:\n\n{reply_text}"
    )

    # Подтверждаем админу
    await update.message.reply_text("✅ Ответ отправлен пользователю.")

    # очищаем
    context.user_data.pop("reply_to_user", None)
    return ConversationHandler.END