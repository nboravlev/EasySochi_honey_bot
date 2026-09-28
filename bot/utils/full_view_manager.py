from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from db.models.products import Product
from utils.escape import safe_html

def render_card(product: Product) -> tuple[str, InlineKeyboardMarkup]:
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
        f"<b>{safe_html(product.name)}</b>\n\n"
        f"💬 {safe_html(product.description) or 'Без описания'}\n\n"
        f"🍯 Тип: {safe_html(product.product_type.name)}\n"
        f"🎲 Цены по размерам:\n{sizes_text}\n"
    )

    # Кнопки
    buttons = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_product_{product.id}")],
        [InlineKeyboardButton("🔄 Внести заново", callback_data=f"redo_product_{product.id}")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    return text, markup
