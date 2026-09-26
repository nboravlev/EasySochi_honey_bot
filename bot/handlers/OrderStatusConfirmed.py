from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from datetime import datetime, timedelta
from db.db_async import get_async_session
from db.models import Order, ProductSize, Size
from utils.escape import safe_html
from utils.message_tricks import cleanup_messages

from handlers.ManagerOrdersConversation import handle_seller_orders

from utils.logging_config import structured_logger

from utils.access import staff_only
from utils.constants import OrderStatus, APIARY_ADDRESS
from config import get_settings

ADMIN_CHAT_ID = get_settings().admin_chat_id


ORDER_STATUS_CREATED = OrderStatus.CREATED
ORDER_STATUS_PROCESSING = OrderStatus.PROCESSING

@staff_only
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
                await query.answer()
                await query.message.reply_text("❌ Заказ не найден.")
                return ConversationHandler.END
            if order.status_id != ORDER_STATUS_CREATED:
                await query.answer()
                await query.message.reply_text(
                    f"Заказ в статусе <b>{safe_html(order.status.name)}</b> \n"
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
                [InlineKeyboardButton("🧭 Показать на карте", callback_data="show_map")]
            ]
            reply_markup_customer = InlineKeyboardMarkup(keyboard_customer)

            await context.bot.send_message(
                chat_id=order.tg_user_id,
                text=(
                    f"🍯 Ваш заказ №{order.id} подтвержден!\n\n"
                    f"{order.product_size.product.name} ({order.product_size.sizes.name}кг х {order.product_count})\n"  # без parse_mode, экранирование не нужно
                    f"Когда заказ будет готов, вы получите уведомление.\n"
                    f"Оплата {order.total_price}₽ при получении переводом или наличными.\n"
                    f"Получение заказа:\n"
                    f"{APIARY_ADDRESS}"
                ),
                reply_markup=reply_markup_customer
            )
            # сообщение ушло покупателю — в очередь очистки менеджера его не кладём
            created_local = order.created_at + timedelta(hours=3)
            manager_text = (
                f"🔔 Заказ #{order.id}🔔\n\n"
                f"🍯: <b>{safe_html(order.product_size.product.name)}</b>\n"
                f"🫙 Размер: {order.product_size.sizes.name}кг\n"
                f"🔢 Количество: {order.product_count}\n"
                f"💰 Стоимость: {order.total_price} ₽\n"
                f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
                f"💬 Комментарий клиента: {safe_html(order.customer_comment) or '—'}\n"
                f"👨: {safe_html(order.user.firstname or order.user.username)}\n"
                f"☎️ Номер: {safe_html(order.user.phone_number) or 'не указан'}"
            )
                # новая клавиатура: только "Готов к выдаче"
            new_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 Заказ готов к выдаче", callback_data=f"order_ready_{order.id}")]
                ])
            await session.commit()

            # «из списка» — только если кнопку нажали в личном кабинете, а не в админ-чате
            from_orders = context.user_data.get("from_orders_list") and query.message.chat.type == "private"

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