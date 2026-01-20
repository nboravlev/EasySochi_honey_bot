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

ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_READY = 4

async def order_ready_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
#    await query.answer()

    try:
        _, _, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
        print(f"DEBUG_ORDER_READY: {query.data}")
        await cleanup_messages(context)

        async with get_async_session() as session:
            result = await session.execute(
                select(Order)
                .options(
                        selectinload(Order.product_size).selectinload(ProductSize.product),
                        selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
                        selectinload(Order.user),  # гость
                        selectinload(Order.status),
                        selectinload(Order.session)
                )
                .where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()
            
            if not order:
                await query.message.reply_text("❌ Бронирование не найдено.")
                return ConversationHandler.END
            if order.status_id != ORDER_STATUS_PROCESSING:
                await query.message.reply_text(
                    f"Бронирование в статусе <b>{order.status.name}</b> \n"
                    f"нельзя перевести в статус Готово к выдаче. Обратитесь к администратору.",
                    parse_mode="HTML"
                )
                return ConversationHandler.END
            lag = datetime.utcnow() - order.created_at
            lag_minutes = int(lag.total_seconds() // 60)
            # updates
            order.status_id = ORDER_STATUS_READY
            order.updated_at = datetime.utcnow()
            order.session.last_action = {"ready_in": lag_minutes}
            await session.commit()

            structured_logger.info(
                "order_status - READY.",
                user_id=order.tg_user_id,
                order_id=order.id,
                context={"ready_delay":lag_minutes}
            )
            #manager_notification
            # 2) Убираем inline-кнопки из того сообщения, где была нажата кнопка (owner message)
            from_orders = context.user_data.get("from_orders_list")
            print(f"DEBUG_FROM_orders_LIST = {from_orders}")
            keyboard_customer = [
                [InlineKeyboardButton("🧭 Показать на карте", callback_data=f"show_map")],
                [InlineKeyboardButton(str("Планирую получить:"), callback_data=f"noop")],
                [InlineKeyboardButton("🟢 сегодня", callback_data=f"pickup_today_{order.id}"),
                InlineKeyboardButton("🟡 завтра", callback_data=f"pickup_tomorrow_{order.id}"),
                InlineKeyboardButton("🔵 завтра+", callback_data=f"pickup_later_{order.id}")]
            ]
            text_customer = (
                    f"💥Ваш заказ №{order.id} ожидает получения!💥\n\n"
                    f"<b>{order.product_size.product.name}</b> ({order.product_size.sizes.name}кг х {order.product_count})\n"
                    f"К оплате <b>{order.total_price}₽</b> переводом или наличными.\n"
                    f"Получение заказа:\n"
                    f"Красная Поляна, ул. Плотинная, д. 4"
                )
            reply_markup_customer = InlineKeyboardMarkup(keyboard_customer)
            msg = await context.bot.send_message(
                chat_id=order.tg_user_id,
                text=text_customer,
                reply_markup=reply_markup_customer,
                parse_mode="HTML"
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

            if from_orders:
                await query.answer(f"Заказ №{order.id} готов к выдаче 🤝", show_alert=True)
                context.user_data["from_orders_list"] = False
                await handle_seller_orders(update, context)
                return ConversationHandler.END
            else:
                await query.answer()  # закрыть callback без алерта
                await query.message.edit_text(
                    text=f"Покупатель получил уведомление, что заказ №{order.id} готов к выдаче",
                    reply_markup=None,
                    parse_mode="HTML"
                )
            


            #await session.commit()
    except Exception as e:
        structured_logger.error("Ошибка при подтверждении готовности заказа",exception=e)
        await query.message.reply_text("❌ Ошибка: неверный ID бронирования")

    return ConversationHandler.END