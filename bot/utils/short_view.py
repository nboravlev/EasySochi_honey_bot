#from bot.db.models.products import Apartment 

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)




def render_apartment_card_short(apartment: Apartment) -> tuple[str, list[InputMediaPhoto] | None, InlineKeyboardMarkup]:
    text = (
        f"<b>{apartment.short_address}</b>\n"
        f"💵 {apartment.price} ₽/ночь\n"
        f"🧍 Макс гостей: {apartment.max_guests}"
    )
    
    photo_id = apartment.images[0].tg_file_id if apartment.images else None
    photo = [InputMediaPhoto(photo_id)] if photo_id else None

    buttons = [
        [InlineKeyboardButton("📄 Подробнее", callback_data=f"apt_{apartment.id}")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    return text, photo, markup
