from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, ApplicationHandlerStop
)
import os

from utils.escape import safe_html


ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

SEND_PROBLEM = 1






async def start_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Опишите ситуацию, и я передам сообщение администратору.")
    context.user_data["awaiting_problem"] = True

    return SEND_PROBLEM


async def process_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_problem"):
        return

    user = update.effective_user
    problem_text = update.message.text.strip()
    admin_message, keyboard = _make_admin_message(user, problem_text)

    # Отправляем в админскую группу
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=admin_message,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await update.message.reply_text("✅ Сообщение передано администратору. Спасибо!")
    context.user_data.pop("awaiting_problem", None)
    # без state диалог оставался в SEND_PROBLEM навсегда
    raise ApplicationHandlerStop(ConversationHandler.END)



#вспомогательная функция
def _make_admin_message(user, problem_text: str) -> tuple[str, InlineKeyboardMarkup]:
    # HTML с экранированием: в Markdown символы _ * [ ` из имени или текста роняли отправку
    text = (
        f"🚨 <b>Сообщение о проблеме</b>\n\n"
        f"👤 Пользователь: <a href=\"tg://user?id={user.id}\">{safe_html(user.first_name) or 'без имени'}</a>\n"
        f"🆔 TG ID: <code>{user.id}</code>\n\n"
        f"📝 Проблема:\n{safe_html(problem_text)}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{user.id}")]
    ])
    return text, keyboard


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ Вы прервали отправку сообщения в поддержку")
    context.user_data.clear()
    return ConversationHandler.END