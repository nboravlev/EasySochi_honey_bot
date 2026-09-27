"""Отклонение заказа продавцом: кнопка «Отклонить» → причина → уведомление покупателю."""
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from db.db_async import get_async_session
from domain.order_flow import InvalidTransition
from services import order_texts
from services.orders import MAX_REASON_LENGTH, decline, get_order
from utils.access import staff_only
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.message_tricks import cleanup_messages

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

    await query.message.reply_text(
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
        try:
            decline(order, reason, actor_id=update.effective_user.id)
        except InvalidTransition:
            await update.message.reply_text(
                f"⛔ Нельзя отклонить заказ в статусе <b>{safe_html(order.status.name)}</b>.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            return ConversationHandler.END
        await session.commit()

    structured_logger.info(
        "Order declined", order_id=order.id, action="order_declined",
        context={"customer_id": order.tg_user_id, "reason_length": len(reason)},
    )
    try:
        await context.bot.send_message(
            chat_id=order.tg_user_id, text=order_texts.customer_declined(order), parse_mode="HTML"
        )
        confirm_text = "‼️ Заказ отклонен, гость уведомлен."
    except Exception as exc:
        structured_logger.warning(
            "Failed to notify customer about decline", order_id=order.id,
            action="order_notify_failed", context={"error": str(exc)},
        )
        confirm_text = "‼️ Заказ отклонен, но гость не получил уведомление (возможно, заблокировал бота)."

    await update.message.reply_text(confirm_text, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def cancel_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Передумали отклонять."""
    await update.message.reply_text("Отмена заявки отменена.", reply_markup=ReplyKeyboardRemove())
    context.user_data.pop("decline_order_id", None)
    return ConversationHandler.END
