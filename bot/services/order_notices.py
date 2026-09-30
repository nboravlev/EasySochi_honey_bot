"""Уведомления о заказе в нейтральном формате (domain.messages) — одни и те же для бота, витрины и админки."""
from db.models import Order
from domain.messages import Button, OutMessage, Recipient, ToShopStaff, ToUser
from services import order_texts

# уведомление: кому, что, какое событие (для журнала очереди)
Notice = tuple[Recipient, OutMessage, str]


def map_button(order: Order) -> Button:
    return Button(
        "🧭 Показать на карте", action=f"show_map_{order.location_id}" if order.location_id else "show_map"
    )


def new_order_for_staff(order: Order) -> OutMessage:
    """Карточка нового заказа в служебный чат магазина: подтвердить или отклонить."""
    return OutMessage(
        order_texts.manager_card(order, f"🔔 Новый заказ #{order.id}🔔"),
        [[Button("✅ Подтвердить", action=f"confirm_order_{order.id}"),
          Button("Отклонить ❌", action=f"decline_order_{order.id}")]],
    )


def order_placed_for_customer(order: Order) -> OutMessage:
    """Покупателю в чат: заказ с сайта / Mini App принят. Дальше статусы приходят сюда же."""
    return OutMessage(
        f"✅ Ваш заказ №{order.id} создан!\n\n"
        f"{order_texts.product_line(order)}\n"
        f"💰 {order_texts.rub(order.total_price)}\n"
        f"📍 Самовывоз: {order_texts.pickup_address(order)}\n\n"
        "Ожидайте уведомление от продавца."
    )


def confirmed(order: Order) -> list[Notice]:
    message = OutMessage(order_texts.customer_confirmed(order), [[map_button(order)]])
    return [(ToUser(order.customer_id), message, "order_confirmed")]


def ready(order: Order) -> list[Notice]:
    message = OutMessage(order_texts.customer_ready(order), [
        [map_button(order)],
        [Button("Планирую получить:", action="noop")],
        [Button("🟢 сегодня", action=f"pickup_today_{order.id}"),
         Button("🟡 завтра", action=f"pickup_tomorrow_{order.id}"),
         Button("🔵 завтра+", action=f"pickup_later_{order.id}")],
    ])
    return [(ToUser(order.customer_id), message, "order_ready")]


def received(order: Order) -> list[Notice]:
    return [
        (ToUser(order.customer_id),
         OutMessage("❤️ Спасибо, что выбрали наш мёд! Будем рады видеть вас снова!"), "order_received"),
        (ToShopStaff(order.shop_id),
         OutMessage(f"Заказ №{order.id} выдан покупателю.\nОплачено {order_texts.rub(order.total_price)}"),
         "order_received"),
    ]


def declined(order: Order) -> list[Notice]:
    return [(ToUser(order.customer_id), OutMessage(order_texts.customer_declined(order)), "order_declined")]
