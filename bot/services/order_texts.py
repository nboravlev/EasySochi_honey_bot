"""Тексты о заказе для покупателя и менеджера. Пользовательские поля экранируются здесь — один раз."""
from decimal import Decimal

from db.models import Order
from utils.constants import APIARY_ADDRESS
from utils.escape import safe_html
from utils.timeutils import format_local


def rub(amount: Decimal | int | float | None) -> str:
    """15000 → «15 000 ₽», 1500.50 → «1 500,50 ₽»."""
    value = Decimal(amount or 0)
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return text.replace(",", " ").replace(".", ",") + " ₽"


def product_line(order: Order) -> str:
    size = order.product_size
    return f"{safe_html(size.product.name)} ({size.sizes.name}кг × {order.product_count})"


def customer_name(order: Order) -> str:
    return safe_html(order.user.firstname or order.user.username) or "без имени"


def draft_card(order: Order) -> str:
    """Карточка черновика у покупателя (HTML)."""
    size = order.product_size
    return (
        f"<b>{safe_html(size.product.name)}</b>\n"
        f"🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝\n"
        f"Цена ({size.sizes.name}кг) – {rub(size.price)}\n"
        f"Количество: {order.product_count}\n"
        f"Тара: {safe_html(size.sizes.package.name)}\n"
        f"Комментарий: {safe_html(order.customer_comment) or '-'}"
    )


def manager_card(order: Order, title: str) -> str:
    """Карточка заказа для продавца (HTML): новый заказ, подтверждённый и т.п."""
    size = order.product_size
    return (
        f"{title}\n\n"
        f"🍯: <b>{safe_html(size.product.name)}</b>\n"
        f"🫙 Размер: {size.sizes.name}кг\n"
        f"🔢 Количество: {order.product_count}\n"
        f"💰 Стоимость: {rub(order.total_price)}\n"
        f"⏰ Создан: {format_local(order.created_at)}\n"
        f"💬 Комментарий клиента: {safe_html(order.customer_comment) or '—'}\n"
        f"👨: {customer_name(order)}\n"
        f"☎️ Номер: {safe_html(order.user.phone_number) or 'не указан'}"
    )


def manager_list_card(order: Order, index: int, total: int) -> str:
    """Карточка в «Мои заказы» (HTML)."""
    status_name = safe_html(order.status.name) if order.status else "—"
    return (
        f"‼️ Cтатус <b>{status_name}</b> ‼️\n\n"
        f"Заказ №{order.id}\n"
        f"{product_line(order)}\n"
        f"⏰ Создан: {format_local(order.created_at)}\n"
        f"💰 Стоимость: {rub(order.total_price)}\n"
        f"💬 Комментарий клиента: {safe_html(order.customer_comment) or '—'}\n"
        f"👨: {customer_name(order)}\n"
        f"☎️ Номер: {safe_html(order.user.phone_number) or 'не указан'}\n\n"
        f"📍 {index + 1} из {total}"
    )


def customer_confirmed(order: Order) -> str:
    return (
        f"🍯 Ваш заказ №{order.id} подтвержден!\n\n"
        f"{product_line(order)}\n"
        f"Когда заказ будет готов, вы получите уведомление.\n"
        f"Оплата {rub(order.total_price)} при получении переводом или наличными.\n"
        f"Получение заказа:\n"
        f"{safe_html(APIARY_ADDRESS)}"
    )


def customer_ready(order: Order) -> str:
    return (
        f"💥Ваш заказ №{order.id} ожидает получения!💥\n\n"
        f"<b>{product_line(order)}</b>\n"
        f"К оплате <b>{rub(order.total_price)}</b> переводом или наличными.\n"
        f"Получение заказа:\n"
        f"{safe_html(APIARY_ADDRESS)}"
    )


def manager_pickup_planned(order: Order, pickup_date: str) -> str:
    size = order.product_size
    return (
        f"🔔 Заказ #{order.id}🔔\n\n"
        f"🍯: <b>{safe_html(size.product.name)}({size.sizes.name}кг)</b>\n"
        f"🔢 Количество: {order.product_count}\n"
        f"💰 Стоимость: {rub(order.total_price)}\n"
        f"Покупатель подтвердил, что придет за медом:\n"
        f"<b>{pickup_date}</b> (ориентировочно)\n"
        f"👨: {customer_name(order)}\n"
        f"☎️: {safe_html(order.user.phone_number) or 'не указан'}"
    )


def customer_declined(order: Order) -> str:
    return (
        f"❌ Ваш заказ №{order.id} отклонен продавцом.\n"
        f"{product_line(order)}\n"
        f"⏰ Создан: {format_local(order.created_at)}\n"
        f"Cтоимость: {rub(order.total_price)}\n"
        f"Причина: {safe_html(order.manager_comment)}\n\n"
        f"Хотите выбрать другой товар?\n"
        "👉 /honey_buy"
    )
