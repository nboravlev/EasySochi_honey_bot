from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from datetime import datetime

from db.db_async import get_async_session

from db.models.orders import Booking
from db.models.products import Apartment
from db.models.users import User

from sqlalchemy import select

async def send_booking_chat_history(booking_id: int,update: Update):
    async with get_async_session() as session:
        # Получаем бронирование
        result = await session.execute(
            select(Booking).where(Booking.id == booking_id)
        )
        booking = result.scalar_one_or_none()
        if not booking:
            await update.message.reply_text("❌ Бронирование не найдено.")
            return

        # Получаем все сообщения по бронированию
        result = await session.execute(
            select(BookingChat)
            .where(BookingChat.booking_id == booking_id)
            .order_by(BookingChat.created_at.asc())
        )
        messages = result.scalars().all()

    message = update.message or update.callback_query.message

    if not messages:
        await message.reply_text("📭 История сообщений пуста.")
        return

    # Сборка текста истории
    text_lines = [f"📜 10 сообщений из истории бронирования №{booking_id}:"]
    for msg in messages[-10:]:  # последние 10 сообщений
        sender = "👤 Арендатор" if msg.sender_tg_id == booking.tg_user_id else "🏠 Собственник"
        timestamp = msg.created_at.strftime("%d.%m %H:%M")
        text_lines.append(f"{timestamp} | {sender}:\n{msg.message_text}")

    await message.reply_text("\n\n".join(text_lines))
