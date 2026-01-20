
from telegram import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    Update, 
    ReplyKeyboardRemove, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler
)
from db.db_async import get_async_session
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime
from handlers.RegistrationConversation import route_after_login

from db.models import Session

from utils.message_tricks import send_message, add_message_to_cleanup, cleanup_messages

from utils.logging_config import structured_logger, LoggingContext

(ASK_DATE,
 ASK_TIME) = range(2)


#=======Приглашение на дегустацию============
async def honey_invite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update,"Введите дату мероприятия (в формате ДД.ММ.ГГГГ):"
    )
    return ASK_DATE

async def honey_invite_ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        event_date = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите дату в виде ДД.ММ.ГГГГ:")
        return ASK_DATE

    context.user_data["event_date"] = event_date
    await update.message.reply_text("Теперь введите время начала (в формате ЧЧ:ММ):")
    return ASK_TIME

# 3️⃣ Получаем время и рассылаем приглашения
async def honey_invite_ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        event_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите время в виде ЧЧ:ММ:")
        return ASK_TIME

    event_date = context.user_data["event_date"]
    event_datetime = datetime.combine(event_date, event_time)

    async with get_async_session() as session:
        # Получаем пользователей
        result = await session.execute(
            select(Session.id,Session.tg_user_id).where(
                Session.role_id == 3,
                Session.sent_message == False
            )
        )
        rows = result.fetchall()

        session_ids = [row.id for row in rows]
        users_to_notify = [row.tg_user_id for row in rows]

        if not users_to_notify:
            await update.message.reply_text("❗ Нет пользователей для рассылки.")
            return ConversationHandler.END

        message_text = (
            f"🍯 <b>Приглашение на дегустацию мёда!</b>\n\n"
            f"Уважаемые гости, приглашаем вас посетить нашу дегустацию мёда "
            f"<b>{event_date.strftime('%d.%m.%Y')}</b> в <b>{event_time.strftime('%H:%M')}</b> "
            f"по адресу: <i>Сочи, Красная Поляна, ул. Плотинная 2</i> 🐝\n\n"
            f"Если вы планируете прийти — напишите «Приду» в чат поддержки /help 💬"
        )

        sent_count = 0
        failed = 0

        # Рассылаем сообщения
        for user_id in users_to_notify:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode="HTML"
                )
                sent_count += 1
            except Exception as e:
                structured_logger.warning(
                    "Failed to send invite",
                    user_id=user_id,
                    action="invite_failed",
                    context={"error": str(e)}
                )
                failed += 1

        # Обновляем статусы в БД
        await session.execute(
            sa_update(Session)
            .where(Session.id.in_(session_ids))
            .values(
                sent_message=True,
                last_action={"event_datetime": event_datetime.isoformat()},
                updated_at=datetime.utcnow()
            )
        )
        await session.commit()

    # Подтверждение админу
    await update.message.reply_text(
        f"✅ Рассылка завершена.\n"
        f"Отправлено: {sent_count}\n"
        f"Ошибок: {failed}",
        reply_markup=ReplyKeyboardRemove()
    )

    structured_logger.info(
        "Honey invite campaign completed",
        action="honey_invite_sent",
        context={
            "sent": sent_count,
            "failed": failed,
            "event_datetime": str(event_datetime)
        }
    )

    return ConversationHandler.END
        
#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END
