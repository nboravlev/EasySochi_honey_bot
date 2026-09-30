"""/help: пользователь описывает проблему → сообщение в служебный чат магазина-витрины с кнопкой «Ответить»."""
from telegram import Update
from telegram.ext import (
    ConversationHandler, ContextTypes, ApplicationHandlerStop
)

from db.db_async import get_async_session
from domain.enums import Provider
from domain.messages import Button, OutMessage, ToShopStaff
from services import identity, notifications, shops
from utils.escape import safe_html
from utils.delivery import deliver, log_no_channel

SEND_PROBLEM = 1


async def start_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Опишите ситуацию, и я передам сообщение администратору.")
    context.user_data["awaiting_problem"] = True

    return SEND_PROBLEM


async def process_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_problem"):
        return

    tg_user = update.effective_user
    problem_text = update.message.text.strip()

    # в служебный чат магазина-витрины; ответ администратора придёт человеку по users.id
    # (написать в поддержку можно и без регистрации — тогда заводим пользователя по Telegram-аккаунту)
    async with get_async_session() as session:
        shop_id = await shops.storefront_shop_id(session)
        user, _ = await identity.get_or_create_user(
            session, Provider.TELEGRAM, tg_user.id, username=tg_user.username
        )
        pending = []
        if shop_id is not None:
            rows = await notifications.enqueue(
                session, ToShopStaff(shop_id), _make_admin_message(tg_user, user.id, problem_text), "user_problem"
            )
            pending = notifications.ids_of(rows)
        await session.commit()

    if not pending:
        log_no_channel(ToShopStaff(shop_id or 0), "user_problem")
    result = await deliver(context.bot, pending)
    context.user_data.pop("awaiting_problem", None)
    if result.sent or result.queued:
        await update.message.reply_text("✅ Сообщение передано администратору. Спасибо!")
    else:
        await update.message.reply_text("Не удалось передать сообщение. Попробуйте позже.")
    # без state диалог оставался в SEND_PROBLEM навсегда
    raise ApplicationHandlerStop(ConversationHandler.END)


#вспомогательная функция
def _make_admin_message(tg_user, user_id: int, problem_text: str) -> OutMessage:
    # HTML с экранированием: в Markdown символы _ * [ ` из имени или текста роняли отправку
    text = (
        f"🚨 <b>Сообщение о проблеме</b>\n\n"
        f"👤 Пользователь: <a href=\"tg://user?id={tg_user.id}\">{safe_html(tg_user.first_name) or 'без имени'}</a>\n"
        f"🆔 TG ID: <code>{tg_user.id}</code>\n\n"
        f"📝 Проблема:\n{safe_html(problem_text)}"
    )
    return OutMessage(text, [[Button("💬 Ответить", action=f"reply_{user_id}")]])


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ Вы прервали отправку сообщения в поддержку")
    context.user_data.clear()
    return ConversationHandler.END
