from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db.db_async import get_async_session
from services import catalog


async def product_offers(product_id: int) -> tuple[list[catalog.Offer], str | None]:
    """Размеры с ценами и обложка товара."""
    async with get_async_session() as session:
        return await catalog.offers(session, product_id), await catalog.cover_image(session, product_id)


def offer_label(offer: catalog.Offer) -> str:
    return f"{offer.size_name}кг – {float(offer.price):.0f}₽"


async def get_product_sizes_keyboard(product_id: int) -> tuple[list[catalog.Offer], InlineKeyboardMarkup, str | None]:
    """Размеры товара, клавиатура выбора размера (select_size_<id>) и обложка для карточки покупателя."""
    sizes, image_file_id = await product_offers(product_id)
    # Формируем одну строку кнопок для размеров
    size_buttons = [
        InlineKeyboardButton(offer_label(s), callback_data=f"select_size_{s.product_size_id}")
        for s in sizes
    ]

    keyboard = [size_buttons]  # все размеры в одном ряду
    keyboard.append([InlineKeyboardButton("🔙 Начать сначала", callback_data="honey_buy")])

    return sizes, InlineKeyboardMarkup(keyboard), image_file_id


async def build_order_keyboard(order,total_price):
    """Формируем клавиатуру заказа"""
    qty_buttons = [
        InlineKeyboardButton("➖", callback_data=f"update_qty_-_{order.id}"),
        InlineKeyboardButton(str(order.product_count), callback_data="noop"),
        InlineKeyboardButton("➕", callback_data=f"update_qty_+_{order.id}")
    ]
    keyboard_rows = [qty_buttons]
    # добавляем кнопку комментария, только если комментария ещё нет
    if not order.customer_comment:
        keyboard_rows.append(
            [InlineKeyboardButton("📨 Комментарий к заказу", callback_data=f"customer_comment_{order.id}")]
        )

    keyboard_rows.append(
        [InlineKeyboardButton(f"🛎 Заказать мед {int(total_price)} ₽", callback_data=f"pay_{order.id}")]
    )

    return InlineKeyboardMarkup(keyboard_rows)

