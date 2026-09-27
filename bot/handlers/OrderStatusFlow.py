"""Кнопки смены статуса заказа: подтвердить, готов, «заберу сегодня/завтра», выдан.

Статус меняется через services.orders.transition (таблица переходов в domain.order_flow)
и фиксируется до уведомлений: если покупатель заблокировал бота, действие продавца не откатывается.
"""
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import get_settings
from db.db_async import get_async_session
from db.models import Order
from domain.enums import OrderStatus
from domain.order_flow import InvalidTransition
from handlers.ManagerOrdersConversation import handle_seller_orders
from services import order_texts
from services.orders import get_order, registered_user_id, transition
from utils.access import staff_only
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.message_tricks import cleanup_messages
from utils.timeutils import local_today


def _order_id(data: str) -> int:
    return int(data.rsplit("_", 1)[-1])


async def _reject(query, order: Order | None) -> int:
    """Заказа нет или действие уже неактуально (повторный клик, заказ отклонён и т.п.)."""
    if order is None:
        await query.answer("❌ Заказ не найден.", show_alert=True)
    else:
        status = order.status.name if order.status else "—"
        await query.answer(f"Заказ №{order.id} в статусе «{status}» — это действие уже недоступно.", show_alert=True)
    return ConversationHandler.END


async def _notify(context: ContextTypes.DEFAULT_TYPE, order: Order, chat_id: int, **kwargs) -> bool:
    try:
        await context.bot.send_message(chat_id=chat_id, **kwargs)
        return True
    except Exception as exc:
        structured_logger.warning(
            "Failed to notify about order",
            order_id=order.id,
            action="order_notify_failed",
            context={"chat_id": chat_id, "error": str(exc)},
        )
        return False


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _from_orders_list(query, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # «из списка» — только если кнопку нажали в личном кабинете, а не в админ-чате
    return bool(context.user_data.get("from_orders_list")) and query.message.chat.type == "private"


@staff_only
async def order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продавец подтвердил заказ: CREATED → PROCESSING."""
    query = update.callback_query
    await cleanup_messages(context)
    async with get_async_session() as session:
        order = await get_order(session, _order_id(query.data))
        try:
            if order is None:
                raise LookupError
            seller_id = await registered_user_id(session, update.effective_user.id)
            waited = transition(order, OrderStatus.PROCESSING, actor_id=seller_id)
        except (LookupError, InvalidTransition):
            return await _reject(query, order)
        await session.commit()

    structured_logger.info(
        "Seller accepted order",
        order_id=order.id,
        action="order_confirmed",
        context={"customer_id": order.tg_user_id, "waited_minutes": _minutes(waited)},
    )
    delivered = await _notify(
        context, order, order.tg_user_id,
        text=order_texts.customer_confirmed(order),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧭 Показать на карте", callback_data="show_map")]]),
    )
    warning = "" if delivered else "\n⚠️ Покупатель не получил уведомление (возможно, заблокировал бота)."

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
    async with get_async_session() as session:
        order = await get_order(session, _order_id(query.data))
        try:
            if order is None:
                raise LookupError
            prepared_in = transition(order, OrderStatus.READY)
        except (LookupError, InvalidTransition):
            return await _reject(query, order)
        order.session.last_action = {"ready_in": _minutes(prepared_in)}
        await session.commit()

    structured_logger.info(
        "Order is ready",
        order_id=order.id,
        action="order_ready",
        context={"customer_id": order.tg_user_id, "prepared_minutes": _minutes(prepared_in)},
    )
    delivered = await _notify(
        context, order, order.tg_user_id,
        text=order_texts.customer_ready(order),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧭 Показать на карте", callback_data="show_map")],
            [InlineKeyboardButton("Планирую получить:", callback_data="noop")],
            [InlineKeyboardButton("🟢 сегодня", callback_data=f"pickup_today_{order.id}"),
             InlineKeyboardButton("🟡 завтра", callback_data=f"pickup_tomorrow_{order.id}"),
             InlineKeyboardButton("🔵 завтра+", callback_data=f"pickup_later_{order.id}")],
        ]),
    )
    warning = "" if delivered else "\n⚠️ Покупатель не получил уведомление (возможно, заблокировал бота)."

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

    async with get_async_session() as session:
        order = await get_order(session, int(order_id))
        # кнопку может нажать только покупатель и только один раз
        if order is None or order.tg_user_id != update.effective_user.id:
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
        "Customer planned pickup",
        order_id=order.id,
        action="order_pickup_planned",
        context={"pickup_date": pickup_date, "reacted_minutes": _minutes(waited)},
    )
    # сообщение в админ-чат не кладём в очистку покупателя: иначе его /start удалял бы кнопку продавца
    await _notify(
        context, order, get_settings().admin_chat_id,
        text=order_texts.manager_pickup_planned(order, pickup_date),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Покупатель получил заказ", callback_data=f"order_complit_{order.id}")]]
        ),
    )
    seller_phone = (order.manager.phone_number if order.manager else None) or get_settings().seller_contact
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
    async with get_async_session() as session:
        order = await get_order(session, _order_id(query.data))
        try:
            if order is None:
                raise LookupError
            transition(order, OrderStatus.RECEIVED, actor_id=update.effective_user.id)
        except (LookupError, InvalidTransition):
            return await _reject(query, order)
        await session.commit()

    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # клавиатура уже снята
    structured_logger.info(
        "Order handed over", order_id=order.id, action="order_received",
        context={"customer_id": order.tg_user_id, "amount": order.total_price},
    )
    await _notify(context, order, order.tg_user_id, text="❤️ Спасибо, что выбрали наш мёд! Будем рады видеть вас снова!")
    await _notify(
        context, order, get_settings().admin_chat_id,
        text=f"Заказ №{order.id} выдан покупателю.\nОплачено {order_texts.rub(order.total_price)}",
    )
    return ConversationHandler.END
