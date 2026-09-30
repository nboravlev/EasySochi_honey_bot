"""Действия продавца с заказом — одинаковые для кнопок бота и админки.

Смена статуса (через domain.order_flow) и уведомления, которые из неё следуют. Вызывающий
загружает заказ (services.orders.get_order), проверяет права на магазин, ставит уведомления
в очередь той же сессией и коммитит.
"""
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from db.models import Order
from domain.enums import OrderStatus
from services import order_notices
from services.order_notices import Notice
from services.orders import decline, transition


class StaffAction(StrEnum):
    CONFIRM = "confirm"      # CREATED → PROCESSING
    READY = "ready"          # PROCESSING → READY
    RECEIVED = "received"    # READY / CUSTOMER_NOTIFIED → RECEIVED
    DECLINE = "decline"      # до выдачи → DECLINED (с причиной)


TARGET = {
    StaffAction.CONFIRM: OrderStatus.PROCESSING,
    StaffAction.READY: OrderStatus.READY,
    StaffAction.RECEIVED: OrderStatus.RECEIVED,
    StaffAction.DECLINE: OrderStatus.DECLINED,
}

TITLES = {
    StaffAction.CONFIRM: "подтверждён",
    StaffAction.READY: "готов к выдаче",
    StaffAction.RECEIVED: "выдан",
    StaffAction.DECLINE: "отклонён",
}


@dataclass
class ActionResult:
    order: Order
    spent: timedelta          # сколько заказ пробыл в прежнем статусе (для логов)
    notices: list[Notice]


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def apply(order: Order, action: StaffAction, actor_id: int | None, reason: str = "") -> ActionResult:
    """Выполнить действие; недопустимое для текущего статуса — domain.order_flow.InvalidTransition.

    Заказ должен быть загружен со связями (get_order): тексты уведомлений их используют.
    """
    if action == StaffAction.DECLINE:
        spent = decline(order, reason, actor_id=actor_id)
        return ActionResult(order, spent, order_notices.declined(order))

    spent = transition(order, TARGET[action], actor_id=actor_id)
    if action == StaffAction.CONFIRM:
        notices = order_notices.confirmed(order)
    elif action == StaffAction.READY:
        order.session.last_action = {"ready_in": minutes(spent)}
        notices = order_notices.ready(order)
    else:
        notices = order_notices.received(order)
    return ActionResult(order, spent, notices)
