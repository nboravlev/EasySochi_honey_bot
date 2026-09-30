"""Ответ администратора на сообщение о проблеме: кнопка «Ответить» (reply_<users.id>) → текст → пользователю."""
from telegram import Update
from telegram.ext import (
    ConversationHandler, ContextTypes
)

from domain.messages import OutMessage, ToUser
from utils.access import staff_only
from utils.escape import safe_html
from utils.delivery import notify, undelivered_note

REPLY_WAITING = 1


@staff_only
async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # сохраняем получателя (users.id) в context.user_data админа
    context.user_data["reply_to_user"] = int(query.data.rsplit("_", 1)[-1])

    await update.effective_chat.send_message("✍️ Введите ответ пользователю:")

    return REPLY_WAITING


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_user_id = context.user_data.pop("reply_to_user", None)
    if not target_user_id:
        await update.message.reply_text("❌ Ошибка: нет пользователя для ответа.")
        return ConversationHandler.END

    reply_text = update.message.text.strip()
    delivery = await notify(
        context.bot, ToUser(target_user_id),
        OutMessage(f"📩 Ответ администратора:\n\n{safe_html(reply_text)}"), "support_reply",
    )
    note = undelivered_note(delivery, who="Пользователь")
    await update.message.reply_text(note.strip() or "✅ Ответ отправлен пользователю.")
    return ConversationHandler.END
