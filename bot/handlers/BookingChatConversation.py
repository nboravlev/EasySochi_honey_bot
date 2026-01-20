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

from bot.db.models.orders import Order
from bot.db.models.products import Product
from db.models.users import User

from utils.escape import safe_html
from utils.message_tricks import sanitize_message
from utils.booking_chat_message_history import send_booking_chat_history

from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)

from sqlalchemy import select, update as sa_update

from sqlalchemy.orm import selectinload


# Состояния
(
    GO_TO_CHAT,
    BOOKING_CHAT
) = range(2)



# ✅ 2. Обработчик кнопки Перейти в чат

async def open_booking_chat_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    

    callback_data = query.data
    try:
        booking_id = int(query.data.split("_")[-1])
        context.user_data["chat_booking_id"] = booking_id
        context.user_data["callback_data"] = callback_data
    except (ValueError, IndexError) as e:

        await query.message.reply_text("Ошибка: не найден ID бронирования")
        return ConversationHandler.END

    # Редактируем сообщение с кнопкой (убираем кнопку)
    await query.edit_message_reply_markup(reply_markup=None)

    await send_booking_chat_history(booking_id, update)

    #делаем отметку, что историю ему уже показана
    shown_key = f"history_shown_{booking_id}"
    context.user_data[shown_key] = True
    
    # Отправляем приглашение в чат
    await query.message.reply_text(
        f"💬 Вы вошли в чат бронирования №{booking_id}.\n"
        "Отправьте свое сообщение.\n\n"
        "Для выхода используйте команду /cancel"
    )
    
    return BOOKING_CHAT

# ✅ 3. Обработка сообщений в чате
async def booking_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    booking_id = context.user_data.get("chat_booking_id")
    if not booking_id:
        return  # пользователь не в контексте чата бронирования

    text = update.message.text
    clean_text = sanitize_message(text)
    user_tg_id = update.effective_user.id

    async with get_async_session() as session:
        # 1. Получаем объект бронирования
        result = await session.execute(
            select(Order).where(Order.id == booking_id)
        )
        booking = result.scalar_one_or_none()
        if not booking:
            await update.message.reply_text("❌ Бронирование не найдено.")
            return

        # 2. Получаем информацию о гостях и владельце
        renter_id = booking.tg_user_id
        if not renter_id:
            await update.message.reply_text("❌ Арендатор не найден.")
            return ConversationHandler.END

        result = await session.execute(
            select(Product).where(Product.id == booking.apartment_id)
        )
        apartment = result.scalar_one_or_none()
        if not apartment:
            await update.message.reply_text("❌ Объект не найден.")
            return ConversationHandler.END


        owner_id = apartment.owner_tg_id
        if not owner_id:
            await update.message.reply_text("❌ Владелец не найден.")
            return ConversationHandler.END

        callback_data = context.user_data.get("callback_data")
        logger.info(
        "Booking chat opened",
        extra={
            "action": "open_booking_chat",
            "status": "success",
            "callback_data": callback_data,
            "booking_id": booking_id,
            "initiator_tg_user_id": user_tg_id,
            "renter_id": renter_id or None,
            "owner_id": owner_id or None
        }
    )

        # 3. Определяем роль отправителя
        if user_tg_id == renter_id:
            sender_id = renter_id
            recipient_tg_id = owner_id
            sender_type = "guest"
        elif user_tg_id == owner_id:
            sender_id = owner_id
            recipient_tg_id = renter_id
            sender_type = "owner"
        else:
            await update.message.reply_text("❌ Вы не участник этого бронирования")
            return BOOKING_CHAT

        # 4. Сохраняем сообщение
        chat_msg = BookingChat(
            booking_id=booking_id,
            sender_tg_id=sender_id,
            message_text=text[:255],
            created_at=datetime.utcnow()
        )
        session.add(chat_msg)
        await session.commit()

    # 5. Отправляем сообщение с КНОПКОЙ ДЛЯ ОТВЕТА
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ответить", callback_data=f"chat_booking_enter_{booking_id}")]
    ])

    await context.bot.send_message(
        chat_id=recipient_tg_id,
        text=f"💬 Новое сообщение по бронированию №{booking_id}:\n\n{clean_text}\n\n"
             f"ℹ️ Отправитель: {'Гость' if sender_type == 'guest' else 'Собственник'}",
        reply_markup=reply_markup
    )

    return BOOKING_CHAT

async def enter_booking_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"ENTER_BOOKING_CHAT: Callback received: '{query.data}'")
    # Извлекаем ID бронирования из callback_data
    try:
        # Извлекаем ID бронирования из callback_data
        booking_id = int(query.data.split("_")[-1])
        logger.info(f"ENTER_BOOKING_CHAT: Extracted booking_id: {booking_id}")
        
        # Сохраняем в user_data
        context.user_data["chat_booking_id"] = booking_id
        # Проверяем, показывали ли историю именно для этого booking_id
        shown_key = f"history_shown_{booking_id}"
        if not context.user_data.get(shown_key):
            await send_booking_chat_history(booking_id, update)
            context.user_data[shown_key] = True
        # Отправляем подтверждение
        await query.edit_message_text(
            f"💬 Вы вошли в чат бронирования №{booking_id}\n"
            "Отправьте ваше сообщение..."
        )
        
        logger.info(f"ENTER_BOOKING_CHAT: Successfully entered chat for booking {booking_id}")
        return BOOKING_CHAT
        
    except Exception as e:
        logger.error(f"ENTER_BOOKING_CHAT: Error processing callback: {e}")
        await query.edit_message_text("❌ Ошибка при входе в чат")
        return ConversationHandler.END
    
async def exit_booking_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "chat_booking_id" in context.user_data:
        del context.user_data["chat_booking_id"]
    else:
        context.user_data.clear()

    await update.message.reply_text("Вы вышли из чата бронирования",reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END