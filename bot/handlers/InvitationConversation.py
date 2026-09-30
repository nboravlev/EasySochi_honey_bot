"""Дегустации: менеджер назначает дату → приглашения листу ожидания → ответ «Приду» / «Не смогу»."""
from datetime import datetime

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from db.db_async import get_async_session
from handlers.RegistrationConversation import route_after_login
from domain.messages import Button, OutMessage, ToUser
from services import notifications, shops, tasting
from utils.access import get_actor, manager_only, user_id_for_telegram
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.message_tricks import cleanup_messages, send_message
from utils.delivery import SEND_INTERVAL_SEC, deliver
from utils.timeutils import BUSINESS_TZ, format_local, utcnow

(ASK_DATE,
 ASK_TIME) = range(2)


def invitation_text(starts_at: datetime, address: str | None) -> str:
    return (
        f"🍯 <b>Приглашение на дегустацию мёда!</b>\n\n"
        f"Уважаемые гости, приглашаем вас посетить нашу дегустацию мёда "
        f"<b>{format_local(starts_at, '%d.%m.%Y')}</b> в <b>{format_local(starts_at, '%H:%M')}</b> "
        f"по адресу: <i>{safe_html(address) or 'уточните у продавца'}</i> 🐝\n\n"
        f"Придёте? Ответьте кнопкой ниже — так мы подготовим нужное количество мёда 💬"
    )


def rsvp_buttons(signup_id: int) -> list[list[Button]]:
    return [[
        Button("✅ Приду", action=f"tasting_yes_{signup_id}"),
        Button("❌ Не смогу", action=f"tasting_no_{signup_id}"),
    ]]


#=======Приглашение на дегустацию============
@manager_only
async def honey_invite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await send_message(update, "Введите дату мероприятия (в формате ДД.ММ.ГГГГ):")
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


async def honey_invite_ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаёт мероприятие, переводит лист ожидания в «приглашён» и рассылает приглашения."""
    text = update.message.text.strip()
    try:
        event_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите время в виде ЧЧ:ММ:")
        return ASK_TIME

    # менеджер вводит время пасеки (Москва), в БД — UTC
    starts_at = datetime.combine(context.user_data["event_date"], event_time, tzinfo=BUSINESS_TZ)
    if starts_at <= utcnow():
        await update.message.reply_text("❌ Это время уже прошло. Введите дату заново (ДД.ММ.ГГГГ):")
        return ASK_DATE

    # дегустацию проводит магазин менеджера (у владельца платформы — магазин-витрина)
    actor = await get_actor(update)
    shop_id = await actor.work_shop_id()
    if shop_id is None:
        await update.message.reply_text("Не удалось определить магазин для дегустации.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async with get_async_session() as session:
        if await tasting.waiting_count(session, shop_id) == 0:
            await update.message.reply_text("❗ Нет пользователей для рассылки.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        event, invited = await tasting.invite_waiting(session, shop_id, starts_at, created_by=actor.user_id)
        location = await shops.pickup_location(session, shop_id)
        # приглашения — в очередь в одной транзакции с мероприятием: не потеряются при сбое Telegram
        message_text = invitation_text(starts_at, location.address if location else None)
        pending, unreachable = [], 0
        for record in invited:
            rows = await notifications.enqueue(
                session, ToUser(record.user_id), OutMessage(message_text, rsvp_buttons(record.id)), "tasting_invite"
            )
            pending += notifications.ids_of(rows)
            unreachable += not rows
        await session.commit()

    result = await deliver(context.bot, pending, pace=SEND_INTERVAL_SEC)
    failed = result.failed + unreachable
    await update.message.reply_text(
        f"✅ Рассылка завершена.\n"
        f"Отправлено: {result.sent}\n"
        + (f"Отправим позже (Telegram не ответил): {result.queued}\n" if result.queued else "")
        + f"Ошибок: {failed}\n"
        f"Ответы гостей — в статистике меню менеджера.",
        reply_markup=ReplyKeyboardRemove()
    )
    structured_logger.info(
        "Tasting invite campaign completed",
        action="tasting_invite_sent",
        context={"sent": result.sent, "queued": result.queued, "failed": failed, "event_id": event.id,
                 "starts_at": starts_at},
    )
    return ConversationHandler.END


async def tasting_rsvp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ гостя на приглашение; передумать можно до начала мероприятия."""
    query = update.callback_query
    _, answer, signup_id = query.data.split("_")
    going = answer == "yes"

    async with get_async_session() as session:
        user_id = await user_id_for_telegram(update.effective_user.id)
        record = await tasting.respond(session, int(signup_id), user_id, going) if user_id else None
        await session.commit()

    if record is None:
        await query.answer("Это приглашение уже неактуально.", show_alert=True)
        return ConversationHandler.END

    structured_logger.info(
        "Tasting RSVP", action="tasting_rsvp",
        context={"signup_id": record.id, "event_id": record.event_id, "going": going},
    )
    await query.answer(
        "🍯 Ждём вас на дегустации!" if going else "Жаль! Запишитесь снова, когда будет удобно 🙂",
        show_alert=True,
    )
    # оставляем кнопки: гость может передумать
    return ConversationHandler.END


#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END
