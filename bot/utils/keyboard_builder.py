from decimal import Decimal
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from db.models import ProductSize, Size, Image
from db.db_async import get_async_session
import calendar
from datetime import date, timedelta

# Префиксы для callback
CB_PREFIX = "CAL"
CB_SELECT = f"{CB_PREFIX}_SELECT"
CB_NAV = f"{CB_PREFIX}_NAV"

def build_calendar(year: int, month: int, check_in=None, check_out=None):
    """Строит inline-календарь"""
    cal = calendar.Calendar(firstweekday=0)
    keyboard = []

    # Шапка с месяцем
    keyboard.append([InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="IGNORE")])

    # Дни недели
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(d, callback_data="IGNORE") for d in week_days])

    # Сетка дней
    for week in cal.monthdatescalendar(year, month):
        row = []
        for day in week:
            if day.month != month:
                row.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
            else:
                text = str(day.day)

                # Подсветка выбранного диапазона
                if check_in and check_out and check_in <= day <= check_out:
                    text = f"✔️{day.day}"
                elif check_in and day == check_in:
                    text = f"✔️{day.day}"
                elif check_out and day == check_out:
                    text = f"🔴{day.day}"

                row.append(InlineKeyboardButton(text, callback_data=f"{CB_SELECT}:{day.isoformat()}"))
        keyboard.append(row)

    # Навигация
    prev_month = (date(year, month, 1) - timedelta(days=1)).replace(day=1)
    next_month = (date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=1)).replace(day=1)
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f"{CB_NAV}:{prev_month.year}:{prev_month.month}"),
        InlineKeyboardButton("▶️", callback_data=f"{CB_NAV}:{next_month.year}:{next_month.month}")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_types_keyboard(types, selected):
    """Формирует inline-клавиатуру с отметками выбранных типов."""
    keyboard = []
    for t in types:
        mark = "📍 " if t["id"] in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{t['name']}", callback_data=f"type_{t['id']}")])
    
    # Добавляем кнопку подтверждения
    keyboard.append([InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_types")])
    return keyboard

def build_price_filter_keyboard():
    return [
        [InlineKeyboardButton("0 – 3000 ₽", callback_data="price_0_3000")],
        [InlineKeyboardButton("3000 – 5900 ₽", callback_data="price_3000_5900")],
        [InlineKeyboardButton("6000+ ₽", callback_data="price_6000_plus")],
        [InlineKeyboardButton("💰 Без фильтра", callback_data="price_all")]
    ]

def build_add_keyboard(adds, selected):
    """Формирует inline-клавиатуру с отметками выбранных типов."""
    keyboard = []

    for a in adds:
        mark = "📌 " if a["id"] in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{a['name']}", callback_data=f"type_{a['id']}")])

    # Добавляем кнопки в зависимости от выбранных
    if selected:
        # Есть выбранные — только Подтвердить
        keyboard.append([InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_adds")])
    else:
        # Нет выбранных — Подтвердить и Пропустить
        keyboard.append([
            InlineKeyboardButton("➡️ Пропустить", callback_data="skip")
        ])

    return keyboard

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
                ProductSize.is_active == True
            )
            .order_by(ProductSize.price.asc())
        )
        sizes = result.mappings().all()

                # Получаем первое активное фото
        image_result = await session.execute(
            select(Image.tg_file_id)
            .where(Image.product_id == product_id, Image.is_active == True)
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

