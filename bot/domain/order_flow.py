"""Жизненный цикл заказа: какие смены статуса разрешены.

DRAFT → CREATED → PROCESSING → READY → CUSTOMER_NOTIFIED → RECEIVED
Отклонить можно до выдачи (CREATED/PROCESSING/READY), черновик — только истечь.
"""
from domain.enums import OrderStatus

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.CREATED, OrderStatus.EXPIRED}),
    OrderStatus.CREATED: frozenset({OrderStatus.PROCESSING, OrderStatus.DECLINED}),
    OrderStatus.PROCESSING: frozenset({OrderStatus.READY, OrderStatus.DECLINED}),
    # выдать можно и без ответа покупателя «сегодня/завтра»
    OrderStatus.READY: frozenset({OrderStatus.CUSTOMER_NOTIFIED, OrderStatus.RECEIVED, OrderStatus.DECLINED}),
    OrderStatus.CUSTOMER_NOTIFIED: frozenset({OrderStatus.RECEIVED}),
}

FINAL_STATUSES = frozenset({OrderStatus.RECEIVED, OrderStatus.DECLINED, OrderStatus.EXPIRED})
# заказы «в работе» у продавца: мешают снять товар с продажи
ACTIVE_STATUSES = frozenset({
    OrderStatus.CREATED, OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.CUSTOMER_NOTIFIED,
})


class InvalidTransition(Exception):
    def __init__(self, current: int, target: int):
        self.current = OrderStatus(current)
        self.target = OrderStatus(target)
        super().__init__(f"{self.current.name} → {self.target.name} is not allowed")


def can_transition(current: int, target: int) -> bool:
    return OrderStatus(target) in ALLOWED_TRANSITIONS.get(OrderStatus(current), frozenset())


def check_transition(current: int, target: int) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
