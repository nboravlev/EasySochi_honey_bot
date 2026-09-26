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

from utils.constants import OrderStatus, BUSINESS_TZ

ORDER_STATUS_PROCESSING = OrderStatus.PROCESSING
ORDER_STATUS_READY = OrderStatus.READY
ORDER_STATUS_CUSTOMER_NOTIFIED = OrderStatus.CUSTOMER_NOTIFIED
SELLER_CONTACT = os.getenv("SELLER_CONTACT")

async def customer_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупатель жмет на кнопку, когда заберет заказ"""
    await cleanup_messages(context)
    query = update.callback_query

    #await query.edit_message_reply_markup(reply_markup=None)
    try:

        _, processing_time_str,order_id_str = query.data.split("_")
        order_id = int(order_id_str)

        # «сегодня» считаем по Москве, а не по времени контейнера (UTC)
        today = datetime.now(BUSINESS_TZ)
        if processing_time_str == "today":
            processing_date = today
        elif processing_time_str == "tomorrow":
            processing_date = today + timedelta(days=1)
        else:  # later
            processing_date = today + timedelta(days=2)

        async with get_async_session() as session:
            result = await session.execute(
                select(Order)
                .options(
                        selectinload(Order.product_size).selectinload(ProductSize.product),
                        selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
                        selectinload(Order.user),  # гость
                        selectinload(Order.manager), #продавец
                        selectinload(Order.status),
                        selectinload(Order.session)
                )
                .where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()
            
            # кнопку может нажать только покупатель и только один раз, пока заказ в статусе READY
            if not order or order.tg_user_id != update.effective_user.id:
                await query.answer("Заказ не найден.", show_alert=True)
                return ConversationHandler.END
            if order.status_id != ORDER_STATUS_READY:
                await query.answer("Продавец уже знает о вашем визите 👍", show_alert=True)
                return ConversationHandler.END
            await query.answer()

            # updates
            lag = datetime.utcnow() - order.updated_at
            lag_minutes = int(lag.total_seconds() // 60)
            order.status_id = ORDER_STATUS_CUSTOMER_NOTIFIED
            order.updated_at = datetime.utcnow()
            order.session.last_action = {
                "event": "customer_confirm",
                "expected_recieving": processing_date.isoformat()
            }
            await session.flush()
            structured_logger.info(
                "Customer_accepted_readiness",
                user_id=order.tg_user_id,
                order_id=order.id,
                action="order_pickup_planned",
                context={"Customer_acted_in":lag_minutes}
            )

            manager_text = (
                f"🔔 Заказ #{order.id}🔔\n\n"
                f"🍯: <b>{safe_html(order.product_size.product.name)}({order.product_size.sizes.name}кг)</b>\n"
                f"🔢 Количество: {order.product_count}\n"
                f"💰 Стоимость: {order.total_price} ₽\n"
                f"Покупатель подтвердил, что придет за медом:\n"
                f"<b>{processing_date.strftime('%d.%m.%Y')}</b> (ориентировочно)\n"
                f"👨: {safe_html(order.user.firstname or order.user.username)}\n"
                f"☎️: {safe_html(order.user.phone_number) or 'не указан'}"
            )
            new_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Покупатель получил заказ", callback_data=f"order_complit_{order.id}")]
            ])

            # сообщение в админ-чат не кладём в очистку покупателя:
            # иначе его /start удалял кнопку «Покупатель получил заказ» у продавца
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=manager_text,
                reply_markup=new_keyboard,
                parse_mode='HTML'
            )

            seller_phone = (order.manager.phone_number if order.manager else None) or SELLER_CONTACT
            customer_message = (
                "Продавец проинформирован,\n"
                "что примерная дата получения заказа:\n"
                f"<b>{processing_date.strftime('%d.%m.%Y')}</b>\n"
                + (f"Номер телефона для связи\n☎️: {safe_html(seller_phone)}" if seller_phone else "")
            )

            # уведомляем клиента
            msg = await context.bot.send_message(
                chat_id=order.tg_user_id,
                text=customer_message,
                parse_mode="HTML"
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

            await session.commit()

    except Exception as e:
        structured_logger.error(
            "Ошибка при подтверждении готовности заказа",
            user_id=update.effective_user.id,
            action="order_pickup_error",
            exception=e
        )
        await query.message.reply_text("❌ Не удалось передать продавцу дату. Попробуйте ещё раз или напишите в /help")
        
    
    return ConversationHandler.END
    