from db.models import Order, Product, ProductSize, Size, Image
from datetime import timedelta
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from db.db_async import get_async_session
from sqlalchemy import select
from sqlalchemy.orm import selectinload


from utils.escape import safe_html

from utils.access import is_owner



ORDER_STATUS_CREATED = 1
ORDER_STATUS_CUSTOMER_INFORMED = 2
ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_READY = 4
ORDER_STATUS_PAYED = 5 #продавец нажал на кнопку, когда отдал заказ
ORDER_STATUS_DECLINED = 6
ORDER_STATUS_EXPIRED = 7
ORDER_STATUS_DRAFT = 8

def prepare_owner_orders_cards(current_order: Order, current_index: int, total: int, status_filters: list = None) -> tuple[str, str | None, InlineKeyboardMarkup]:
    """Возвращает текст и клавиатуру для карточки."""

    created_local = current_order.created_at + timedelta(hours=3)

            # Формируем текст сообщения
    text = (
        f"‼️ Cтатус <b>{safe_html(current_order.status.name)}</b> ‼️\n\n"
        f"Заказ №{current_order.id}\n"
        f"{safe_html(current_order.product_size.product.name)} ({current_order.product_size.sizes.name} x {current_order.product_count})\n"
        f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
        f"💰 Стоимость: {current_order.total_price} ₽\n"
        f"💬 Комментарий клиента: {safe_html(current_order.customer_comment) or '—'}\n"
        f"👨: {safe_html(current_order.user.firstname or current_order.user.username)}\n"
        f"☎️ Номер: {safe_html(current_order.user.phone_number) or 'не указан'}\n\n"
        f"📍 {current_index+1} из {total}"

    )


            # кнопки навигации
    buttons = []

    # --- навигация ---
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Предыдущий", callback_data=f"owner_order_prev_{current_index-1}")
        )
    if current_index < total - 1:
        nav_buttons.append(
            InlineKeyboardButton("➡️ Следующий", callback_data=f"owner_order_next_{current_index+1}")
        )
    if nav_buttons:
        buttons.append(nav_buttons)

    # --- действия по заказу ---
    action_buttons = []
    if current_order.status.id == ORDER_STATUS_CREATED:
        action_buttons.append(
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_order_{current_order.id}")
        )
        action_buttons.append(
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_order_{current_order.id}")
        )
    elif current_order.status.id == ORDER_STATUS_PROCESSING:
        action_buttons.append(
            InlineKeyboardButton("📦 Заказ готов к выдаче", callback_data=f"order_ready_{current_order.id}")
        )

    if action_buttons:
        buttons.append(action_buttons)

    # --- фильтры по статусам ---
    filter_buttons = []
    if status_filters:
        for label, status_id in status_filters.items():
            filter_buttons.append(
                InlineKeyboardButton(label, callback_data=f"owner_order_filter_{status_id or 'all'}")
            )
        buttons.append(filter_buttons)

    # --- возврат в меню ---
    buttons.append([InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_menu")])

    markup = InlineKeyboardMarkup(buttons)
    
    return text, markup

async def fetch_seller_products(user_tg_id: int, is_admin: bool):
    """
    
    :param user_tg_id: ID продавца
    :param is_admin: True, если админ, False — обычный продавец
    :param status_filter: список статусов для фильтрации. Если None — возвращаем все.
    """
    async with get_async_session() as session:
        stmt = select(Product).options(
            selectinload(Product.product_sizes).selectinload(ProductSize.sizes),
            selectinload(Product.user),
            selectinload(Product.product_type)
        ).where(
        Product.is_active.is_(True),
        Product.is_draft.is_(False)
        ).order_by(Product.created_at.asc())

        
        # фильтр по продавцу, если это не админ
        if not is_admin:
            stmt = stmt.where(Product.created_by == user_tg_id)

        result = await session.execute(stmt)
        products = result.scalars().all()
        return products


async def get_manager_product_sizes_keyboard(product_id: int) -> tuple[list[dict], InlineKeyboardMarkup]:
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
            callback_data=f"edit_sizeprice_{s['product_size_id']}"
        )
        for s in sizes
    ]

    keyboard = [size_buttons]  # все размеры в одном ряду
    keyboard.append([InlineKeyboardButton("🚫 Снять с продажи", callback_data=f"product_delete_{product_id}")])

    return sizes, InlineKeyboardMarkup(keyboard), image_file_id


async def fetch_seller_orders(user_tg_id: int, is_admin: bool, status_filter: list = None):
    """
    Возвращает заказы продавца с возможностью фильтрации по статусу.
    
    :param user_tg_id: ID продавца
    :param is_admin: True, если админ, False — обычный продавец
    :param status_filter: список статусов для фильтрации. Если None — возвращаем все.
    """
    async with get_async_session() as session:
        is_admin = is_owner(user_tg_id)
        stmt = select(Order).options(
            selectinload(Order.product_size).selectinload(ProductSize.product),
            selectinload(Order.product_size).selectinload(ProductSize.sizes),
            selectinload(Order.user),
            selectinload(Order.status)
        ).order_by(Order.created_at.asc())

        # фильтр по статусу
        if status_filter:
            stmt = stmt.where(Order.status_id.in_(status_filter))
        
        # фильтр по продавцу, если это не админ
        if not is_admin:
            stmt = stmt.join(ProductSize, Order.product_size_id == ProductSize.id)\
                    .join(Product, ProductSize.product_id == Product.id)\
                    .where(Product.created_by == user_tg_id)

        result = await session.execute(stmt)
        orders = result.scalars().all()
        return orders