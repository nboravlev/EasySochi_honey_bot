from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton
)
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload

from datetime import datetime, timedelta, timezone
from db.db_async import get_async_session
from db.models import Order, Product, ProductSize, Size
from utils.escape import safe_html
from utils.message_tricks import add_message_to_cleanup, cleanup_messages

from handlers.ManagerOrdersConversation import handle_seller_orders

from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)

import os 

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not (ADMIN_CHAT_ID):
    raise RuntimeError("Admin chat id did not set in environment variables")

from utils.access import staff_only
from utils.constants import OrderStatus

DECLINE_REASON = 1
MAX_REASON_LENGTH = 255  # orders.manager_comment VARCHAR(255)

ORDER_STATUS_DECLINED = OrderStatus.DECLINED
# отклонить можно только незавершённый заказ (прежний чёрный список [2,5,6,7,8,9] в виде белого)
DECLINABLE_STATUSES = (OrderStatus.CREATED, OrderStatus.PROCESSING, OrderStatus.READY)


@staff_only
async def booking_decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    # Разбор данных из callback
    data_parts = query.data.split("_")
    order_id = int(data_parts[-1])  # ID брони

    context.user_data["decline_order_id"] = order_id
    await cleanup_messages(context)
    # 2) Убираем inline-кнопки из того сообщения, где была нажата кнопка (owner message)
    try:
        # Это удалит клавиатуру под исходным сообщением
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # клавиатура уже снята

    # Запрашиваем причину
    keyboard = [[KeyboardButton("отправка причины")]]
    await query.message.reply_text(
        "❌ Укажите причину отклонения заявки (макс. 255 символов):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )

    return DECLINE_REASON


async def booking_decline_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    if not reason or reason.lower() == "отправка причины":
        reason = "Причина не указана"
    else:
        # сообщения ниже уходят без parse_mode — храним исходный текст, без HTML-сущностей
        reason = reason[:MAX_REASON_LENGTH]

    order_id = context.user_data.get("decline_order_id")


    async with get_async_session() as session:

        # Загружаем бронь с зависимостями
        result = await session.execute(
            select(Order)
            .options(
                    selectinload(Order.product_size).selectinload(ProductSize.product),
                    selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
                    selectinload(Order.user),  # гость
                    selectinload(Order.status)
            )
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            await update.message.reply_text("❌ Заказ не найден.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        if order.status_id not in DECLINABLE_STATUSES:
            await update.message.reply_text(
                f"⛔ Нельзя отклонить заказ в статусе <b>{safe_html(order.status.name)}</b>.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
            return ConversationHandler.END
          # Обновляем статус и причину
        order.status_id = ORDER_STATUS_DECLINED
        order.updated_at = datetime.utcnow()
        order.manager_comment = reason
        await session.commit()

    # Определяем инициатора
    initiator_tg_id = update.effective_user.id
    guest_tg_id = order.tg_user_id
    owner_tg_id = order.product_size.product.created_by

    
    created_local = order.created_at + timedelta(hours=3)
    if initiator_tg_id == guest_tg_id:
        # Отмену делает гость → уведомляем владельца
        await context.bot.send_message(
            chat_id=owner_tg_id,
            text=(
                f"❌ Гость отменил заказ №{order.id}\n"
                f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
                f"{order.product_size.product.name} ({order.product_size.sizes.name}кг х {order.product_count})\n"
                f"Cтоимость: {order.total_price}₽ \n"
                f"Причина: {reason}"
            )
        )
        confirm_text = "✅ Вы отменили заказ, владелец уведомлён."
    else:
        # Отмену делает владелец → уведомляем гостя
        await context.bot.send_message(
            chat_id=guest_tg_id,
            text=(
                f"❌ Ваше заказ №{order.id} отклонен продавцом.\n"
                f"{order.product_size.product.name} ({order.product_size.sizes.name}кг х {order.product_count})\n"
                f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
                f"Cтоимость: {order.total_price}₽\n"
                f"Причина: {reason}\n\n"
                f"Хотите выбрать другой товар?\n"
                "👉 /honey_buy"
            )
        )
        confirm_text = "‼️ Заказ отклонен, гость уведомлен."

    await update.message.reply_text(confirm_text, reply_markup=ReplyKeyboardRemove())

    # Чистим временные данные
    context.user_data.pop("decline_order_id", None)


    return ConversationHandler.END


# ✅ Only one function: booking confirmation



async def cancel_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the decline process"""
    await update.message.reply_text(
        "Отмена заявки отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.pop("decline_order_id", None)
    return ConversationHandler.END
