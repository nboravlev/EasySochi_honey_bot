from datetime import datetime, timedelta
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from db.db_async import get_async_session
from db.models import Order, DrinkSize, Session
from utils.logging_config import log_function_call, LogExecutionTime, get_logger
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# Константы
ORDER_STATUS_DRAFT = 8      # "черновик"
ORDER_STATUS_EXPIRED = 7    # "время истекло"


@log_function_call(action="check_expired_orders")
async def check_expired_order(context):
    """Проверка и обработка просроченных заказов"""
    logger = get_logger(__name__)
    bot = context.bot

    try:
        async with get_async_session() as session:
            expire_time = datetime.utcnow() - timedelta(minutes=10)

            stmt = (
                select(Order)
                .options(
                    selectinload(Order.status),
                    selectinload(Order.drink_size).selectinload(DrinkSize.drink)
                )
                .where(
                    and_(
                        Order.status_id == ORDER_STATUS_DRAFT,
                        Order.updated_at < expire_time,
                        Order.is_active == True
                    )
                )
            )

            result = await session.execute(stmt)
            expired_orders = result.scalars().all()

            if not expired_orders:
                logger.info(
                    f"No expired bookings found (status_id={ORDER_STATUS_DRAFT}, timeout=10m)",
                    extra={"action": "check_expired_orders"}
                )
                return

            order_ids = [o.id for o in expired_orders[:10]]
            logger.info(
                f"Found {len(expired_orders)} expired bookings to process",
                extra={
                    "action": "check_expired_booking",
                    "booking_ids": order_ids + (["..."] if len(expired_orders) > 10 else [])
                }
            )

            for order in expired_orders:
                order.status_id = ORDER_STATUS_EXPIRED
                order.updated_at = datetime.utcnow()

            await session.commit()

            for order in expired_orders:
                with LogExecutionTime(
                    "notify_timeout",
                    logger,
                    user_id=order.tg_user_id
                ):
                    await notify_timeout(bot, order)

    except Exception as e:
        logger.exception(
            f"Ошибка при обработке просроченных заказов: {e}",
            extra={"action": "check_expired_orders"}
        )


async def notify_timeout(bot, order):
    """Уведомление пользователя о том, что заказ истёк + удаление последнего сообщения"""
    logger = get_logger(__name__)
    guest_chat_id = order.tg_user_id
    created_local = (order.created_at + timedelta(hours=3)).replace(second=0, microsecond=0)
    created_str = created_local.strftime("%Y-%m-%d %H:%M")

    # Удаляем последнее сообщение из сессии, если есть
    async with get_async_session() as session:
        if order.session_id:
            session_obj = await session.get(Session, order.session_id)
            if session_obj and session_obj.last_action:
                last_msg_id = session_obj.last_action.get("message_id")
                if last_msg_id:
                    try:
                        await bot.delete_message(chat_id=guest_chat_id, message_id=last_msg_id)
                        logger.info(f"Deleted last message {last_msg_id} for user {guest_chat_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete message {last_msg_id}: {e}")

    # Отправляем уведомление о просроченном заказе
    keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🆕 Новый заказ", callback_data="new_order")]
    ])

    await bot.send_message(
        chat_id=guest_chat_id,
        text=f"⏰ Ваш заказ от {created_str} просрочен и был отменён.\nНачните новый заказ.",
        reply_markup=keyboard
    )

    logger.info(
        f"Timeout notifications sent for order {order.id}",
        extra={
            "action": "notify_timeout",
            "order_id": order.id,
            "guest_chat_id": guest_chat_id
        }
    )
