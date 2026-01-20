from db.models.products import Product


from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)


def booking_apartment_card_full(current_apartment: Apartment, current_index: int, total: int) -> tuple[str, str | None, InlineKeyboardMarkup]:
    """Возвращает текст, первую фотографию и клавиатуру для карточки."""
    text = (
        f"<b>{current_apartment.short_address}</b>\n\n"
        f"💬 {current_apartment.description or 'Без описания'}\n\n"
        f"🏷️ Тип: {current_apartment.apartment_type.name}\n"
        f"📍 Этаж: {current_apartment.floor}\n"
        f"🏠 Есть балкон: {'Да' if current_apartment.has_balcony else 'Нет'}\n"
        f"🦎 Можно с животными: {'Да' if current_apartment.pets_allowed else 'Нет'}\n"
        f"🧍‍♂️ Максимум гостей: {current_apartment.max_guests}\n"
        f"💰 Цена: {current_apartment.price} ₽/ночь\n\n"
        f"📍 {current_index+1}/{total}"
    )

    # Медиа
    #media = [InputMediaPhoto(img.tg_file_id) for img in apartment.images[:10]] if apartment.images else None

    photo_id = current_apartment.images[0].tg_file_id if current_apartment.images else None
    media = [InputMediaPhoto(photo_id)] if photo_id else None

    buttons = []
    if current_index > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"apt_prev_{current_index-1}"))
    if current_index < total - 1:
        buttons.append(InlineKeyboardButton("➡️ Следующий", callback_data=f"apt_next_{current_index+1}"))

    buttons = [buttons] if buttons else []
    buttons.append([InlineKeyboardButton("✅ Забронировать", callback_data=f"book_{current_apartment.id}_{current_apartment.price}"),
                   InlineKeyboardButton("🔍 Новый поиск", callback_data="start_search")])

    markup = InlineKeyboardMarkup(buttons)


    return text, media, markup
