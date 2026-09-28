"""Кнопки смены статуса заказа: подтвердить, готов, «заберу сегодня/завтра», выдан.

Статус меняется через services.orders.transition (таблица переходов в domain.order_flow)
и фиксируется до уведомлений: если покупатель заблокировал бота, действие продавца не откатывается.
Действовать от имени магазина может только его персонал (can_manage_shop) — служебный чат
магазина A не управляет заказами магазина B.
"""
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from db.db_async import get_async_session
from db.models import Order
from domain.enums import OrderStatus
from domain.order_flow import InvalidTransition
from handlers.ManagerOrdersConversation import handle_seller_orders
from services import order_texts
from services.orders import get_order, transition
from utils.access import can_manage_shop, deny, get_actor, staff_only
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.message_tricks import cleanup_messages
from utils.telegram_delivery import send_to_shop_staff, send_to_user
from utils.timeutils import local_today

NOT_DELIVERED = "\n⚠️ Покупатель не получил уведомление (возможно, заблокировал бота)."


def _order_id(data: str) -> int:
    return int(data.rsplit("_", 1)[-1])


def _map_button(order: Order) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        "🧭 Показать на карте", callback_data=f"show_map_{order.location_id}" if order.location_id else "show_map"
    )


async def _reject(query, order: Order | None) -> int:
    """Заказа нет или действие уже неактуально (повторный клик, заказ отклонён и т.п.)."""
    if order is None:
        await query.answer("❌ Заказ не найден.", show_alert=True)
    else:
        status = order.status.name if order.status else "—"
        await query.answer(f"Заказ №{order.id} в статусе «{status}» — это действие уже недоступно.", show_alert=True)
    return ConversationHandler.END


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _from_orders_list(query, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # «из списка» — только если кнопку нажали в личном кабинете, а не в служебном чате
    return bool(context.user_data.get("from_orders_list")) and query.message.chat.type == "private"


async def _staff_transition(update: Update, target: OrderStatus):
    """Загрузить заказ, проверить права на его магазин и сменить статус.

    Возвращает (order, время_в_прежнем_статусе) или (order|None, None), если действие не выполнено —
    тогда ответ пользователю уже отправлен.
    """
    query = update.callback_query
    actor = await get_actor(update)
    async with get_async_session() as session:
        order = await get_order(session, _order_id(query.data))
        if order is None:
            await _reject(query, None)
            return None, None
        if not await can_manage_shop(update, order.shop_id):
            await deny(update, f"order_{target.name.lower()}")
            return order, None
        try:
            spent = transition(order, target, actor_id=actor.user_id if actor else None)
        except InvalidTransition:
            await _reject(query, order)
            return order, None
        await session.commit()
    return order, spent


@staff_only
async def order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продавец подтвердил заказ: CREATED → PROCESSING."""
    query = update.callback_query
    await cleanup_messages(context)
    order, waited = await _staff_transition(update, OrderStatus.PROCESSING)
    if waited is None:
        return ConversationHandler.END

    structured_logger.info(
        "Seller accepted order", order_id=order.id, action="order_confirmed",
        context={"customer_id": order.customer_id, "shop_id": order.shop_id, "waited_minutes": _minutes(waited)},
    )
    delivered = await send_to_user(
        context.bot, order.customer_id,
        text=order_texts.customer_confirmed(order), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[_map_button(order)]]),
    )
    warning = "" if delivered else NOT_DELIVERED

    if _from_orders_list(query, context):
        await query.answer(f"Заказ №{order.id} подтвержден 🤝{warning}", show_alert=True)
        context.user_data.pop("from_orders_list", None)
        await handle_seller_orders(update, context)
    else:
        await query.answer()
        await query.edit_message_text(
            text=order_texts.manager_card(order, f"🔔 Заказ #{order.id}🔔") + warning,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📦 Заказ готов к выдаче", callback_data=f"order_ready_{order.id}")]]
            ),
            parse_mode="HTML",
        )
    return ConversationHandler.END


@staff_only
async def order_ready_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продавец собрал заказ: PROCESSING → READY, покупатель выбирает день получения."""
    query = update.callback_query
    await cleanup_messages(context)
    order, prepared_in = await _staff_transition(update, OrderStatus.READY)
    if prepared_in is None:
        return ConversationHandler.END
    async with get_async_session() as session:
        stored = await get_order(session, order.id)
        stored.session.last_action = {"ready_in": _minutes(prepared_in)}
        await session.commit()

    structured_logger.info(
        "Order is ready", order_id=order.id, action="order_ready",
        context={"customer_id": order.customer_id, "shop_id": order.shop_id, "prepared_minutes": _minutes(prepared_in)},
    )
    delivered = await send_to_user(
        context.bot, order.customer_id,
        text=order_texts.customer_ready(order), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [_map_button(order)],
            [InlineKeyboardButton("Планирую получить:", callback_data="noop")],
            [InlineKeyboardButton("🟢 сегодня", callback_data=f"pickup_today_{order.id}"),
             InlineKeyboardButton("🟡 завтра", callback_data=f"pickup_tomorrow_{order.id}"),
             InlineKeyboardButton("🔵 завтра+", callback_data=f"pickup_later_{order.id}")],
        ]),
    )
    warning = "" if delivered else NOT_DELIVERED

    if _from_orders_list(query, context):
        await query.answer(f"Заказ №{order.id} готов к выдаче 🤝{warning}", show_alert=True)
        context.user_data["from_orders_list"] = False
        await handle_seller_orders(update, context)
    else:
        await query.answer()
        await query.edit_message_text(
            text=f"Покупатель получил уведомление, что заказ №{order.id} готов к выдаче{warning}",
            reply_markup=None,
        )
    return ConversationHandler.END


PICKUP_OFFSETS = {"today": 0, "tomorrow": 1, "later": 2}


async def customer_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупатель сообщил, когда заберёт заказ: READY → CUSTOMER_NOTIFIED."""
    query = update.callback_query
    await cleanup_messages(context)
    _, when, order_id = query.data.split("_")
    # «сегодня» — по Москве, а не по времени сервера
    pickup_date = (local_today() + timedelta(days=PICKUP_OFFSETS.get(when, 2))).strftime("%d.%m.%Y")
    actor = await get_actor(update)

    async with get_async_session() as session:
        order = await get_order(session, int(order_id))
        # кнопку может нажать только покупатель и только один раз
        if order is None or actor is None or order.customer_id != actor.user_id:
            await query.answer("Заказ не найден.", show_alert=True)
            return ConversationHandler.END
        try:
            waited = transition(order, OrderStatus.CUSTOMER_NOTIFIED)
        except InvalidTransition:
            await query.answer("Продавец уже знает о вашем визите 👍", show_alert=True)
            return ConversationHandler.END
        order.session.last_action = {"event": "customer_confirm", "expected_recieving": pickup_date}
        await session.commit()

    await query.answer()
    structured_logger.info(
        "Customer planned pickup", order_id=order.id, action="order_pickup_planned",
        context={"pickup_date": pickup_date, "reacted_minutes": _minutes(waited)},
    )
    # сообщение персоналу не кладём в очистку покупателя: иначе его /start удалял бы кнопку продавца
    await send_to_shop_staff(
        context.bot, order.shop_id,
        text=order_texts.manager_pickup_planned(order, pickup_date), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Покупатель получил заказ", callback_data=f"order_complit_{order.id}")]]
        ),
    )
    seller_phone = (order.manager.phone_number if order.manager else None) or order.shop.contact_phone
    await update.effective_chat.send_message(
        "Продавец проинформирован,\nчто примерная дата получения заказа:\n"
        f"<b>{pickup_date}</b>\n"
        + (f"Номер телефона для связи\n☎️: {safe_html(seller_phone)}" if seller_phone else ""),
        parse_mode="HTML",
    )
    return ConversationHandler.END


@staff_only
async def order_complit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продавец выдал заказ: READY/CUSTOMER_NOTIFIED → RECEIVED."""
    query = update.callback_query
    await cleanup_messages(context)
    order, _ = await _staff_transition(update, OrderStatus.RECEIVED)
    if order is None or order.status_id != OrderStatus.RECEIVED:
        return ConversationHandler.END

    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # клавиатура уже снята
    structured_logger.info(
        "Order handed over", order_id=order.id, action="order_received",
        context={"customer_id": order.customer_id, "shop_id": order.shop_id, "amount": order.total_price},
    )
    await send_to_user(context.bot, order.customer_id, text="❤️ Спасибо, что выбрали наш мёд! Будем рады видеть вас снова!")
    await send_to_shop_staff(
        context.bot, order.shop_id,
        text=f"Заказ №{order.id} выдан покупателю.\nОплачено {order_texts.rub(order.total_price)}",
    )
    return ConversationHandler.END
