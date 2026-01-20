from bot.db.models.products import Product
from bot.db.models.orders import Order
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

def prepare_renter_bookings_cards(current_booking: Booking, current_index: int, total: int) -> tuple[str, str | None, InlineKeyboardMarkup]:
    """Возвращает текст и клавиатуру для карточки."""
    apartment = current_booking.apartment

    # Формируем текст
    text = (
        f"<b>{apartment.short_address}</b>\n\n"
        f"💬 {apartment.description}\n\n"
        f"🗝 Статус: <b>{current_booking.booking_type.name}</b>\n"
        f"🏷️ Тип: {apartment.apartment_type.name}\n"
        f"📍 Заезд: {current_booking.check_in}\n"
        f"📍 Выезд: {current_booking.check_out}\n"
        f"🧍‍♂️ Гостей: {current_booking.guest_count}\n"
        f"💰 Стоимость: {current_booking.total_price} ₽\n"
        f"⚡️Идентификатор бронирования: {current_booking.id}\n"
        f"📍 {current_index+1} из {total}"
    )

    # кнопки навигации
    buttons = []
    if current_index > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"book_prev_{current_index-1}"))
    if current_index < total - 1:
        buttons.append(InlineKeyboardButton("➡️ Следующий", callback_data=f"book_next_{current_index+1}"))
    
    buttons = [buttons] if buttons else []
    buttons.append([InlineKeyboardButton("🕊 Написать собственнику", callback_data=f"chat_booking_{current_booking.id}"),
                    InlineKeyboardButton("❌ Отменить", callback_data=f"booking_decline_9_{current_booking.id}")])
    buttons.append([InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_menu")])

    markup = InlineKeyboardMarkup(buttons)
    
    return text, markup