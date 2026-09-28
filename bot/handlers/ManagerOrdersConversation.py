from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from telegram.ext import (
    ContextTypes, 
    ConversationHandler
)
from handlers.RegistrationConversation import route_after_login

from utils.manager_lk_collection import fetch_seller_orders, prepare_owner_orders_cards
from db.db_async import get_async_session
from services.orders import get_order
from utils.message_tricks import cleanup_messages



from utils.access import manager_only
from utils.access import get_actor

from domain.enums import OrderStatus

ORDER_STATUS_CREATED = OrderStatus.CREATED
ORDER_STATUS_PROCESSING = OrderStatus.PROCESSING

VIEW_ORDERS = 1



# колбэки действий над заказом, после которых список показывается заново (см. OrderStatusFlow)
REFRESH_PREFIXES = ("confirm_order_", "order_ready_")


@manager_only
async def handle_seller_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие на кнопку "📨 Мои заказы" и навигацию между карточками заказов.
    Поддерживает фильтрацию по статусам.
    """
    query = update.callback_query
    data = query.data if query else ""
    # менеджер видит заказы своего магазина, владелец платформы — всех
    shop_scope = (await get_actor(update)).shop_scope
    context.user_data["from_orders_list"] = True
    # --- фильтры статусов ---
    status_filters = {
        "Создан": ORDER_STATUS_CREATED,
        "В работе": ORDER_STATUS_PROCESSING,
        "Архив": None
    }
    # архив — всё, что продавец уже обработал; черновики и просроченные корзины заказами не считаются
    archive_statuses = [
        OrderStatus.READY,
        OrderStatus.CUSTOMER_NOTIFIED,
        OrderStatus.DECLINED,
        OrderStatus.RECEIVED,
    ]
    # --- определяем текущий фильтр ---
    current_filter = context.user_data.get("current_filter", ORDER_STATUS_CREATED)

    # --- определяем действие ---
    if data.startswith("honey_orders_") or not query:
        # ✅ Первичный вызов — из меню или напрямую (без query)
        # показываем первый непустой список: новые → в работе → архив
        current_filter = ORDER_STATUS_CREATED
        orders = await fetch_seller_orders(shop_scope, [ORDER_STATUS_CREATED])
        if not orders:
            current_filter = ORDER_STATUS_PROCESSING
            orders = await fetch_seller_orders(shop_scope, [ORDER_STATUS_PROCESSING])
        if not orders:
            current_filter = None
            orders = await fetch_seller_orders(shop_scope, archive_statuses)
        context.user_data["seller_orders"] = orders
        context.user_data["current_index"] = 0
        context.user_data["current_filter"] = current_filter

    elif data.startswith(REFRESH_PREFIXES):
        # заказ только что сменил статус — перечитываем текущий фильтр, позицию сохраняем
        statuses = [current_filter] if current_filter else archive_statuses
        context.user_data["seller_orders"] = await fetch_seller_orders(shop_scope, statuses)

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
            orders = await fetch_seller_orders(shop_scope, [filter_value])
        else:

            orders = await fetch_seller_orders(shop_scope, archive_statuses)

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

    # колбэк смены статуса уже отвечен вызывающим хендлером (с алертом)
    if query and not data.startswith(REFRESH_PREFIXES):
        await query.answer()

    # --- показываем карточку ---
    orders = context.user_data.get("seller_orders", [])  # ID заказов
    if not orders:
        text = "❌ Заказы не найдены."
        # оставляем фильтры и выход в меню, иначе из пустого списка некуда нажать
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(label, callback_data=f"owner_order_filter_{status_id or 'all'}")
             for label, status_id in status_filters.items()],
            [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_menu")]
        ])
        if query:
            try:
                await query.edit_message_text(text, reply_markup=markup)
            except Exception:
                await update.effective_chat.send_message(text, reply_markup=markup)
        else:
            await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup)
        return VIEW_ORDERS

    current_index = context.user_data.get("current_index", 0)
    total = len(orders)
    current_index = max(0, min(current_index, total - 1))
    async with get_async_session() as session:
        current_order = await get_order(session, orders[current_index])
    if current_order is None:  # заказ удалён — перечитываем список при следующем открытии
        context.user_data["seller_orders"] = []
        await update.effective_chat.send_message("Заказ больше не найден. Откройте «Мои заказы» заново.")
        return VIEW_ORDERS

    text, markup = prepare_owner_orders_cards(current_order, current_index, total, status_filters)

    # ✅ Унифицированный вывод (через edit_message_text или send_message)
    if query:
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await update.effective_chat.send_message(text, reply_markup=markup, parse_mode="HTML")
    else:
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup, parse_mode="HTML")

    # остаёмся в VIEW_ORDERS, иначе кнопки «Следующий/Предыдущий» и фильтры не обрабатываются
    return VIEW_ORDERS

#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END