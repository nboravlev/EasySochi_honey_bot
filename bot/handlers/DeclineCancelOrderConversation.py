"""Отклонение заказа продавцом: кнопка «Отклонить» → причина → уведомление покупателю."""
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from db.db_async import get_async_session
from domain.order_flow import InvalidTransition
from services import notifications
from services.order_actions import StaffAction, apply as apply_action
from services.orders import MAX_REASON_LENGTH, get_order
from utils.access import can_manage_shop, get_actor, staff_only
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.message_tricks import cleanup_messages
from utils.delivery import deliver, undelivered_note

DECLINE_REASON = 1
SKIP_REASON_BUTTON = "отправка причины"


@staff_only
async def booking_decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["decline_order_id"] = int(query.data.rsplit("_", 1)[-1])
    await cleanup_messages(context)
    try:
        # убираем кнопки под карточкой, где нажали «Отклонить»
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # клавиатура уже снята

    await update.effective_chat.send_message(
        f"❌ Укажите причину отклонения заявки (макс. {MAX_REASON_LENGTH} символов):",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(SKIP_REASON_BUTTON)]], resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return DECLINE_REASON


async def booking_decline_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    reason = "" if text.lower() == SKIP_REASON_BUTTON else text
    order_id = context.user_data.pop("decline_order_id", None)

    async with get_async_session() as session:
        order = await get_order(session, order_id) if order_id else None
        if order is None:
            await update.message.reply_text("❌ Заказ не найден.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if not await can_manage_shop(update, order.shop_id):
            await update.message.reply_text("🚫 Этот заказ принадлежит другому магазину.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        actor = await get_actor(update)
        try:
            result = apply_action(order, StaffAction.DECLINE, actor.user_id if actor else None, reason)
        except InvalidTransition:
            await update.message.reply_text(
                f"⛔ Нельзя отклонить заказ в статусе <b>{safe_html(order.status.name)}</b>.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            return ConversationHandler.END
        pending = await notifications.enqueue_all(session, result.notices)
        await session.commit()

    structured_logger.info(
        "Order declined", order_id=order.id, action="order_declined",
        context={"customer_id": order.customer_id, "shop_id": order.shop_id, "reason_length": len(reason)},
    )
    note = undelivered_note(await deliver(context.bot, pending), who="Гость")
    confirm_text = f"‼️ Заказ отклонен{note}" if note else "‼️ Заказ отклонен, гость уведомлен."

    await update.message.reply_text(confirm_text, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def cancel_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Передумали отклонять."""
    await update.message.reply_text("Отмена заявки отменена.", reply_markup=ReplyKeyboardRemove())
    context.user_data.pop("decline_order_id", None)
    return ConversationHandler.END
