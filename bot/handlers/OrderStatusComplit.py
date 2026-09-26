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

from utils.access import staff_only
from utils.constants import OrderStatus

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not (ADMIN_CHAT_ID):
    raise RuntimeError("Admin chat id did not set in environment variables")


ORDER_STATUS_RECEIVED = OrderStatus.RECEIVED
# выдать можно готовый заказ, даже если покупатель не нажал «сегодня/завтра»
COMPLETABLE_STATUSES = (OrderStatus.READY, OrderStatus.CUSTOMER_NOTIFIED)


# Менеджер нажал "Заказ получен"
@staff_only
async def order_complit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)

    query = update.callback_query
    await query.answer()

    try:
        # Это удалит клавиатуру под исходным сообщением
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # клавиатура уже снята (повторный клик)

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
                await query.message.reply_text("❌ Заказ не найден.")
                return ConversationHandler.END
            if order.status_id not in COMPLETABLE_STATUSES:
                # повторный клик или заказ отклонён — второй раз «выдавать» и слать сообщения нельзя
                await query.message.reply_text(f"Заказ №{order.id} уже закрыт или ещё не готов к выдаче.")
                return ConversationHandler.END

            # обновляем статус
            order.status_id = ORDER_STATUS_RECEIVED
            order.updated_at = datetime.utcnow()
            # фиксируем выдачу до уведомлений: заблокировавший бота покупатель не должен откатывать продажу
            await session.commit()

            structured_logger.info(
                "Customer get the order",
                user_id=order.tg_user_id,
                order_id=order.id,
                action = "order_received"
            )


            # сообщение клиенту
            customer_message = (
                "❤️ Спасибо, что выбрали наш мёд!"
                "Будем рады видеть вас снова!\n"
            )

            # уведомляем клиента
            try:
                await context.bot.send_message(
                    chat_id=order.tg_user_id,
                    text=customer_message
                )
            except Exception as e:
                structured_logger.warning(
                    "Failed to send thanks to customer",
                    user_id=order.tg_user_id,
                    order_id=order.id,
                    action="order_received_notify_failed",
                    context={"error": str(e)}
                )
            manager_text = (f"Заказ №{order.id} выдан покупателю.\n"
                            f"Оплачено {order.total_price} ₽")

            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=manager_text,
                reply_markup= None,
                parse_mode='HTML'
            )

    except Exception as e:
        structured_logger.error(
            "Ошибка при выдаче заказа",
            user_id=update.effective_user.id,
            action="order_received_error",
            exception=e
        )
        await query.message.reply_text("❌ Ошибка: не найден ID заказа")
        
    return ConversationHandler.END
