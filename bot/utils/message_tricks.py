from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import re

async def send_and_pin_message(bot, chat_id: int, text: str, reply_markup=None):
    """
    Отправляет и закрепляет сообщение в чате.

    :param bot: Экземпляр бота (application.bot)
    :param chat_id: ID чата, где отправляем сообщение
    :param text: Текст сообщения
    :param reply_markup: Опционально — клавиатура или кнопки
    """
    # 1. Отправляем сообщение
    sent_message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup
    )

    # 2. Закрепляем его
    await bot.pin_chat_message(
        chat_id=chat_id,
        message_id=sent_message.message_id,
        disable_notification=False  # True — без уведомления
    )

    return sent_message

async def send_message(update: Update, text: str, reply_markup=None, **kwargs):
    """Универсальная отправка сообщения (поддержка Message и CallbackQuery)."""
    if update.message:
        return await update.message.reply_text(text, reply_markup=reply_markup, **kwargs)
    elif update.callback_query:
        return await update.callback_query.message.reply_text(text, reply_markup=reply_markup, **kwargs)

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

def sanitize_message(text: str) -> str:
    # 9+ цифр подряд → ***
    #text = re.sub(r"\d{9,}", "***", text)
    # email → ***
    text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "***", text)
    # Telegram @username → ***
    text = re.sub(r"@\w{3,}", "***", text)
    # ссылки на мессенджеры → ***
    text = re.sub(r"(t\.me/|wa\.me/|viber://|vk\.com/|instagram\.com/)\S+", "***", text)
    return text