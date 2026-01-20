import os

from datetime import  datetime
from telegram import (
    Update
)
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,

)
from sqlalchemy import select

from db.db_async import get_async_session
from db.models import Order
from utils.logging_config import structured_logger
from utils.message_tricks import  cleanup_messages

ORDER_STATUS_CUSTOMER_NOTIFIED = 2
ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_RECEIVED = 5

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not (ADMIN_CHAT_ID):
    raise RuntimeError("Admin chat id did not set in environment variables")


ORDER_STATUS_RECEIVED = 5


# Менеджер нажал "Заказ получен"
async def order_complit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)

    query = update.callback_query
    await query.answer()

    try:
        # Это удалит клавиатуру под исходным сообщением
        await query.edit_message_reply_markup(reply_markup=None)
    except ValueError:
        await update.message.reply_text("Не удалось убрать клавиатуру.")

    try:
        _, _, order_id_str = query.data.split("_")
        order_id = int(order_id_str)

        async with get_async_session() as session:
            result = await session.execute(
                select(Order)
                .where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()
            
            if not order:
                await query.message.reply_text("❌ Бронирование не найдено.")
                return ConversationHandler.END

            # обновляем статус
            order.status_id = ORDER_STATUS_RECEIVED
            order.updated_at = datetime.utcnow()
            await session.flush()
            
            structured_logger.info(
                "Customer get the order",
                user_id=order.tg_user_id,
                order_id=order.id,
                action = "order complit"
            )
            

            # сообщение клиенту
            customer_message = (
                "❤️ Спасибо, что выбрали наш мёд!"
                "Будем рады видеть вас снова!\n"
            )

            # уведомляем клиента
            await context.bot.send_message(
                chat_id=order.tg_user_id,
                text=customer_message
            )
            manager_text = (f"Заказ №{order.id} выдан покупателю.\n"
                            f"Оплачено {order.total_price} ₽")
            
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=manager_text,
                reply_markup= None,
                parse_mode='HTML'
            )

            await session.commit()

    except Exception as e:
        structured_logger.error("Ошибка при выдаче заказа",exception=e)
        await query.message.reply_text("❌ Ошибка: не найден ID заказа")
        
    return ConversationHandler.END
