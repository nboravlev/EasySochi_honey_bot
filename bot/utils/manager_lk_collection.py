"""Кабинет менеджера: карточки заказов и товаров. Всё — в пределах магазина (shop_scope)."""
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db.db_async import get_async_session
from db.models import Order
from domain.enums import OrderStatus
from services import catalog
from services.order_texts import manager_list_card
from utils.keyboard_builder import offer_label, product_offers

ORDER_STATUS_CREATED = OrderStatus.CREATED
ORDER_STATUS_PROCESSING = OrderStatus.PROCESSING

def prepare_owner_orders_cards(current_order: Order, current_index: int, total: int, status_filters: list = None) -> tuple[str, str | None, InlineKeyboardMarkup]:
    """Возвращает текст и клавиатуру для карточки."""

    text = manager_list_card(current_order, current_index, total)


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


async def fetch_seller_products(shop_scope: int | None):
    """Товары в продаже: магазина менеджера или всех магазинов (shop_scope=None — владелец платформы)."""
    async with get_async_session() as session:
        return await catalog.manager_products(session, shop_scope)


async def get_manager_product_sizes_keyboard(product_id: int) -> tuple[list[catalog.Offer], InlineKeyboardMarkup, catalog.Photo | None]:
    """Размеры товара, клавиатура правки цен (edit_sizeprice_<id>) и снятия с продажи, обложка."""
    sizes, cover = await product_offers(product_id)
    keyboard = [
        [InlineKeyboardButton(offer_label(s), callback_data=f"edit_sizeprice_{s.product_size_id}") for s in sizes],
        [InlineKeyboardButton("🚫 Снять с продажи", callback_data=f"product_delete_{product_id}")],
    ]
    return sizes, InlineKeyboardMarkup(keyboard), cover


async def fetch_seller_orders(shop_scope: int | None, status_filter: list | None = None) -> list[int]:
    """ID заказов магазина (по дате создания). Карточка каждого читается из БД при показе."""
    stmt = select(Order.id).order_by(Order.created_at.asc())
    if status_filter:
        stmt = stmt.where(Order.status_id.in_(status_filter))
    if shop_scope is not None:
        stmt = stmt.where(Order.shop_id == shop_scope)
    async with get_async_session() as session:
        return list((await session.scalars(stmt)).all())
