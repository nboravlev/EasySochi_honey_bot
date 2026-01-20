import os
from datetime import timedelta
from telegram import Update, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import joinedload
from db.db_async import get_async_session
from db.models import Order, Drink, DrinkSize, DrinkAdd, User, OrderAdd
from utils.logging_config import log_function_call, LogExecutionTime, get_logger

ORDER_STATUS_PAYED = 2

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not (ADMIN_CHAT_ID):
    raise RuntimeError("Admin chat id did not set in environment variables")

PAYMENT_TOKEN = os.getenv("UKASSA_TOKEN")

if not (PAYMENT_TOKEN):
    raise RuntimeError("Payment credentials are not set in environment variables")



logger = get_logger(__name__)

@log_function_call(action="Start_payment")
async def pay_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывается при нажатии кнопки 'Оплатить'"""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])

    async with get_async_session() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()

    if not order:
        await query.message.reply_text("❌ Заказ не найден")
        return

    # Telegram принимает цену в минимальных единицах (копейки)
    prices = [LabeledPrice("Кофе", int(order.total_price * 100))]

    await query.message.reply_invoice(
        title="Оплата кофе",
        description=f"Заказ #{order.id}",
        provider_token=PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        payload=str(order.id),  # прокидываем id заказа
        start_parameter="coffee-payment",
    )

@log_function_call(action="payment_status_confirmation")
async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обязательный шаг перед оплатой"""
    query = update.pre_checkout_query
    await query.answer(ok=True)



@log_function_call(action="Payment_notion")
async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывается при успешной оплате"""
    payment = update.message.successful_payment
    order_id = int(payment.invoice_payload)

    async with get_async_session() as session:
        # Обновляем статус
        await session.execute(
            sa_update(Order)
            .where(Order.id == order_id)
            .values(status_id=ORDER_STATUS_PAYED)
        )
        await session.commit()

        # Достаём заказ с деталями
        result = await session.execute(
            select(Order)
            .options(
                joinedload(Order.drink_size).joinedload(DrinkSize.drink).joinedload(Drink.drink_type),
                joinedload(Order.drink_size).joinedload(DrinkSize.sizes),
                joinedload(Order.order_adds).joinedload(OrderAdd.add),
                joinedload(Order.user),
            )
            .where(Order.id == order_id)
        )
        order = result.scalars().first()

    # Сообщение для менеджеров
    created_local = order.created_at + timedelta(hours=3)

    adds_text = ", ".join(add.add.name for add in order.order_adds) if order.order_adds else "—"

    manager_text = (
        f"🧡 Новый заказ #{order.id}💙\n\n"
        f"🔠 Группа: <i>{order.drink_size.drink.drink_type.name}</i>\n"
        f"☕️: <b>{order.drink_size.drink.name}</b>\n"
        f"📏 Размер: {order.drink_size.sizes.name}\n"
        f"🔢 Количество: {order.drink_count}\n"
        f"➕ Добавки: {adds_text}\n"
        f"💰 Оплачено: {order.total_price} ₽\n"
        f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
        f"💬 Комментарий клиента: {order.customer_comment or '—'}\n"
        f"😺: {order.user.firstname or order.user.username}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏳ 3 мин", callback_data=f"take_{order.id}_3"),
            InlineKeyboardButton("⏳ 5 мин", callback_data=f"take_{order.id}_5"),
        ],
        [
            InlineKeyboardButton("⏳ 10 мин", callback_data=f"take_{order.id}_10"),
            InlineKeyboardButton("⏳ 10+ мин", callback_data=f"take_{order.id}_10plus"),
        ]
    ])

    # Уведомляем клиента
    await update.message.reply_text(
        "✅ Оплата прошла успешно! Ожидайте уведомление от менеджера."
    )

    # Сообщение в чат менеджеров
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=manager_text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )