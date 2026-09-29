"""Уведомления о заказе в нейтральном формате (domain.messages) — одни и те же для бота, сайта и Mini App."""
from db.models import Order
from domain.messages import Button, OutMessage
from services import order_texts


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
