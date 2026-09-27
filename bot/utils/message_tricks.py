from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest


async def send_message(update: Update, text: str, reply_markup=None, **kwargs):
    """Универсальная отправка сообщения (поддержка Message и CallbackQuery)."""
    if update.message:
        return await update.message.reply_text(text, reply_markup=reply_markup, **kwargs)
    elif update.callback_query:
        return await update.effective_chat.send_message(text, reply_markup=reply_markup, **kwargs)

async def cleanup_messages(context: ContextTypes.DEFAULT_TYPE):
    """
    Удаляет все сообщения, сохранённые в context.user_data["messages_to_delete"].
    После очистки список сбрасывается.
    """
    messages = context.user_data.get("messages_to_delete", [])
    if not messages:
        return

    for chat_id, msg_id in messages:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except BadRequest:
            # сообщение уже удалено или недоступно
            pass

    context.user_data["messages_to_delete"] = []


async def add_message_to_cleanup(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int):
    """
    Добавляет сообщение в список на будущее удаление.
    """
    if "messages_to_delete" not in context.user_data:
        context.user_data["messages_to_delete"] = []
    context.user_data["messages_to_delete"].append((chat_id, msg_id))

