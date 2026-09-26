from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from db.models import ProductSize, Size, Image
from db.db_async import get_async_session

async def get_product_sizes_keyboard(product_id: int) -> tuple[list[dict], InlineKeyboardMarkup]:
    """
    Возвращает:
    1. Список размеров (для логики) — list[dict]
    2. InlineKeyboardMarkup с кнопками выбора размера

    Кнопка: "<Размер> – <Цена>₽"
    callback_data: "select_size_<drink_size_id>"
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(
                ProductSize.id.label("product_size_id"),
                Size.name.label("size_name"),
                ProductSize.price
            )
            .join(Size, Size.id == ProductSize.size_id)
            .where(
                ProductSize.product_id == product_id,
                ProductSize.is_active.is_(True)
            )
            .order_by(ProductSize.price.asc())
        )
        sizes = result.mappings().all()

                # Получаем первое активное фото
        image_result = await session.execute(
            select(Image.tg_file_id)
            .where(Image.product_id == product_id, Image.is_active.is_(True))
            .order_by(Image.created_at.asc())
            .limit(1)
        )
        image_row = image_result.first()
        image_file_id = image_row[0] if image_row else None

    # Формируем одну строку кнопок для размеров
    size_buttons = [
        InlineKeyboardButton(
            f"{s['size_name']}кг – {float(s['price']):.0f}₽",
            callback_data=f"select_size_{s['product_size_id']}"
        )
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

