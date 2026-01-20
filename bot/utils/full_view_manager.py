from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from db.models.products import Product

def render_card(product: Product) -> tuple[str, list[InputMediaPhoto] | None, InlineKeyboardMarkup]:
    # Формируем текст с размерами и ценами
    if product.product_sizes:
        sizes_text = "\n".join(
            f"{ds.sizes.name}кг - {ds.price} ₽" if ds.price else f"{ds.sizes.name}: нет"
            for ds in product.product_sizes
        )
    else:
        sizes_text = "Нет данных по размерам"


    # Основной текст карточки
    text = (
        f"<b>{product.name}</b>\n\n"
        f"💬 {product.description or 'Без описания'}\n\n"
        f"🍯 Тип: {product.product_type.name}\n"
        f"🎲 Цены по размерам:\n{sizes_text}\n"
    )

    # Фото (берем только первое)
    photos = [InputMediaPhoto(img.tg_file_id) for img in product.images[:1]] if product.images else None

    # Кнопки
    buttons = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_product_{product.id}")],
        [InlineKeyboardButton("🔄 Внести заново", callback_data=f"redo_product_{product.id}")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    return text, photos, markup
