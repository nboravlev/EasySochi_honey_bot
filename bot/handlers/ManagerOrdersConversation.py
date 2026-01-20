from telegram import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    Update, 
    ReplyKeyboardRemove, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler
)
from db.db_async import get_async_session
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime
from handlers.RegistrationConversation import route_after_login

from utils.manager_lk_collection import fetch_seller_orders, prepare_owner_orders_cards, fetch_seller_products, get_manager_product_sizes_keyboard
from utils.message_tricks import send_message, add_message_to_cleanup, cleanup_messages

from utils.logging_config import structured_logger, LoggingContext

from db.models import ProductSize,Product,Session

import os

ORDER_STATUS_CREATED = 1
ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_READY = 4
ORDER_STATUS_CUSTOMER_INFORMED = 2
ORDER_STATUS_DECLINED = 6
ORDER_STATUS_EXPIRED = 7
ORDER_STATUS_RECEIVED = 5

VIEW_ORDERS = 1

OWNER_ID = os.getenv("OWNER_ID")
if not (OWNER_ID):
    raise RuntimeError("Owner chat id did not set in environment variables")



async def handle_seller_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие на кнопку "📨 Мои заказы" и навигацию между карточками заказов.
    Поддерживает фильтрацию по статусам.
    """
    query = update.callback_query
    data = query.data if query else ""
    user_tg_id = update.effective_user.id if update.effective_user else None
    is_admin = str(user_tg_id) == str(OWNER_ID)
    context.user_data["from_orders_list"] = True
    print(f"DEBUG_sellers_ORDERS_callback: {data}, is_ADMIN = {is_admin}, OWNER_ID = {OWNER_ID}, tg_user = {user_tg_id}")
    # --- фильтры статусов ---
    status_filters = {
        "Создан": ORDER_STATUS_CREATED,
        "В работе": ORDER_STATUS_PROCESSING,
        "Архив": None
    }
    archive_statuses = [
        ORDER_STATUS_READY,
        ORDER_STATUS_CUSTOMER_INFORMED,
        ORDER_STATUS_DECLINED,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_RECEIVED
    ]
    # --- определяем текущий фильтр ---
    current_filter = context.user_data.get("current_filter", ORDER_STATUS_CREATED)

    # --- определяем действие ---
    if data.startswith("honey_orders_") or not query:
        # ✅ Первичный вызов — из меню или напрямую (без query)
        orders = await fetch_seller_orders(user_tg_id, is_admin, [ORDER_STATUS_CREATED])
        if not orders:
            orders = await fetch_seller_orders(user_tg_id, is_admin, [ORDER_STATUS_PROCESSING]) 
        elif not orders:
            orders = await fetch_seller_orders(user_tg_id, is_admin, archive_statuses) 
        context.user_data["seller_orders"] = orders
        context.user_data["current_index"] = 0
        context.user_data["current_filter"] = ORDER_STATUS_CREATED

    elif data.startswith("owner_order_next_") or data.startswith("owner_order_prev_"):
        # ✅ Навигация по заказам
        try:
            index = int(data.split("_")[-1])
            context.user_data["current_index"] = index
        except Exception:
            context.user_data["current_index"] = 0

    elif data.startswith("owner_order_filter_"):
        # ✅ Фильтрация
        filter_value = data.split("_")[-1]
        if filter_value in ("all", "None"):
            filter_value = None
        else:
            filter_value = int(filter_value)

        current_filter = filter_value
        context.user_data["current_filter"] = current_filter

        if filter_value:
            orders = await fetch_seller_orders(user_tg_id, is_admin, [filter_value])
        else:

            orders = await fetch_seller_orders(user_tg_id, is_admin, archive_statuses)

        context.user_data["seller_orders"] = orders
        context.user_data["current_index"] = 0

    else:
        # ⚠️ Неизвестный колбэк
        if query:
            await query.answer("⚠️ Неизвестное действие.", show_alert=True)
        else:
            chat_id = update.effective_chat.id
            await context.bot.send_message(chat_id, "⚠️ Неизвестное действие.")
        return ConversationHandler.END

    # --- показываем карточку ---
    orders = context.user_data.get("seller_orders", [])
    if not orders:
        text = "❌ Заказы не найдены."
        if query:
            await query.edit_message_text(text)
        else:
            await context.bot.send_message(update.effective_chat.id, text)
        return VIEW_ORDERS

    current_index = context.user_data.get("current_index", 0)
    total = len(orders)
    current_index = max(0, min(current_index, total - 1))
    current_order = orders[current_index]

    text, markup = prepare_owner_orders_cards(current_order, current_index, total, status_filters)

    # ✅ Унифицированный вывод (через edit_message_text или send_message)
    if query:
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup, parse_mode="HTML")

    return ConversationHandler.END

#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END