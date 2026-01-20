from bot.db.models.products import Product
from bot.db.models.product_types import ProductType
from bot.db.models.orders import Order
from bot.db.models.order_statuses import OrderStatus
from sqlalchemy.orm import selectinload
from db.db_async import get_async_session

from telegram.ext import ContextTypes

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)


def show_booked_appartment(booking: Booking) -> tuple[str, list[InputMediaPhoto] | None]:
    apartment = booking.apartment
    if apartment is None:
        return "<b>❗ Ошибка: данные квартиры не найдены</b>", None




    # Формируем текст
    text = (
        f"<b>{apartment.short_address}</b>\n\n"
        f"💬 {apartment.description}\n\n"
        f"🏷️ Тип: {apartment.apartment_type.name}\n"
        f"📍 Заезд: {booking.check_in}\n"
        f"📍 Выезд: {booking.check_out}\n"
        f"🧍‍♂️ Гостей: {booking.guest_count}\n"
        f"💰 Стоимость: {booking.total_price} ₽\n"
        f"⚡️Номер бронирования: №{booking.id}"
    )

    # Подгружаем фото (если есть)
    photos = None
    if getattr(apartment, "images", None):
        valid_photos = [img.tg_file_id for img in apartment.images if getattr(img, "tg_file_id", None)]
        if valid_photos:
            photos = [InputMediaPhoto(file_id) for file_id in valid_photos[:10]]

    return text, photos
