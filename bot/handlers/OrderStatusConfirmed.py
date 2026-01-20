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

ORDER_STATUS_CREATED = 1
ORDER_STATUS_PROCESSING = 3

async def order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle booking confirmation by owner"""
    query = update.callback_query
   # await query.answer()

    try:
        order_id = int(query.data.split("_")[-1])

        await cleanup_messages(context)

        async with get_async_session() as session:
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
                await query.message.reply_text("❌ Заказ не найден.")
                return ConversationHandler.END
            if order.status_id != ORDER_STATUS_CREATED:
                await query.message.reply_text(
                    f"Заказ в статусе <b>{order.status.name}</b> \n"
                    f"нельзя подтвердить. Обратитесь к администратору.",
                    parse_mode="HTML"
                )
                return ConversationHandler.END

            # ✅ Change status to Confirmed (id=6)
            lag = datetime.utcnow() - order.updated_at
            order.status_id = ORDER_STATUS_PROCESSING
            order.manager_id = update.effective_user.id
            order.updated_at = datetime.utcnow()
            await session.flush()
            #lag = datetime.utcnow() - order.updated_at - надо считать лаг до обновления
            lag_minutes = int(lag.total_seconds() // 60)
            structured_logger.info(
                "seller accept order",
                user_id = order.tg_user_id,
                order_id = order.id,            
                action = "Order accepted",
                context = {'acception_delay':lag_minutes,
                           'seller': order.manager_id}
            )
            # ✅ Send notification to guest with chat button
            keyboard_customer = [
                [InlineKeyboardButton("🧭 Показать на карте", callback_data=f"show_map")]
            ]
            reply_markup_customer = InlineKeyboardMarkup(keyboard_customer)

            msg = await context.bot.send_message(
                chat_id=order.tg_user_id,
                text=(
                    f"🍯 Ваш заказ №{order.id} подтвержден!\n\n"
                    f"{order.product_size.product.name} ({order.product_size.sizes.name}кг х {order.product_count})\n"
                    f"Когда заказ будет готов, вы получите уведомление.\n"
                    f"Оплата {order.total_price}₽ при получении переводом или наличными.\n"
                    f"Получение заказа:\n"
                    f"Красная Поляна, ул. Плотинная, д. 4"
                ),
                reply_markup=reply_markup_customer
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
            created_local = order.created_at + timedelta(hours=3)
            manager_text = (
                f"🔔 Заказ #{order.id}🔔\n\n"
                f"🍯: <b>{order.product_size.product.name}</b>\n"
                f"🫙 Размер: {order.product_size.sizes.name}кг\n"
                f"🔢 Количество: {order.product_count}\n"
                f"💰 Стоимость: {order.total_price} ₽\n"
                f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
                f"💬 Комментарий клиента: {order.customer_comment or '—'}\n"
                f"👨: {order.user.firstname or order.user.username}\n"
                f"☎️ Номер: {order.user.phone_number or 'не указан'}"
            )
                # новая клавиатура: только "Готов к выдаче"
            new_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 Заказ готов к выдаче", callback_data=f"order_ready_{order.id}")]
                ])
            await session.commit()

            from_orders = context.user_data.get("from_orders_list")
            print(f"DEBUG_FROM_orders_LIST = {from_orders}")

            if from_orders:
                await query.answer(f"Заказ №{order.id} подтвержден 🤝", show_alert=True)
                context.user_data.pop("from_orders_list", None)
                await handle_seller_orders(update, context)
                return ConversationHandler.END
            else:
                await query.answer()  # закрыть callback без алерта
                await query.message.edit_text(
                    text=manager_text,
                    reply_markup=new_keyboard,
                    parse_mode="HTML"
                )
                return ConversationHandler.END
            

    except Exception as e:
        structured_logger.error("Ошибка при подтверждении заказа",exception=e)
        await query.message.reply_text("❌ Ошибка: не установлен ID заказа")
        return ConversationHandler.END


# Менеджер нажал "Заказ готов к выдаче"