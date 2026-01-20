from bot.db.models.products import Product
from bot.db.models.orders import Order

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)

from datetime import timedelta

def prepare_owner_orders_cards(current_booking: Booking, current_index: int, total: int) -> tuple[str, str | None, InlineKeyboardMarkup]:
    """Возвращает текст и клавиатуру для карточки."""
    apartment = current_booking.apartment
    timeout_deadline = (current_booking.created_at + timedelta(hours=27)).strftime("%Y-%m-%d %H:%M")  # N + 3 часа GMT
    status = current_booking.booking_type.name
    # Расчет комиссии
    commission_percent = current_booking.apartment.reward/100 or 0
    commission_sum = current_booking.total_price * commission_percent

        # Формируем текст сообщения
    text = (
        f"‼️ Cтатус <b>{status}</b> ‼️\n\n"
        f"Идентификатор бронирования: {current_booking.id}\n"
        f"🏠 ID объекта: {apartment.id}\n"
        f"🏠 Адрес: {current_booking.apartment.short_address}\n"
        f"📅 Заезд: {current_booking.check_in.strftime('%Y-%m-%d')}\n"
        f"📅 Выезд: {current_booking.check_out.strftime('%Y-%m-%d')}\n"
        f"👥 Гостей: {current_booking.guest_count}\n"
        f"💰 Стоимость: {current_booking.total_price} ₽\n"
        f"💼 Комиссия: {current_booking.apartment.reward}% = {commission_sum:.0f} ₽\n\n"
        f"ℹ️ Комментарий гостя: {current_booking.comments or '—'}"
    )

        # кнопки навигации
    buttons = []
    if current_index > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"owner_book_prev_{current_index-1}"))
    if current_index < total - 1:
        buttons.append(InlineKeyboardButton("➡️ Следующий", callback_data=f"owner_book_next_{current_index+1}"))
    
    buttons = [buttons] if buttons else []
    if status == 'ожидает подтверждения':
        buttons.append([
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"booking_confirm_{current_booking.id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"booking_decline_8_{current_booking.id}")
    ])
    if status == 'подтверждено':
        buttons.append([InlineKeyboardButton("❌ Отменить", callback_data=f"booking_decline_10_{current_booking.id}"),
                        InlineKeyboardButton("🕊 Написать гостю", callback_data=f"chat_booking_{current_booking.id}")])
    buttons.append([InlineKeyboardButton("🔙 Вернуться назад", callback_data="back_to_objects")])

    markup = InlineKeyboardMarkup(buttons)
    
    return text, markup