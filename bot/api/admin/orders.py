"""Заказы в админке: список с фильтрами и поиском, карточка, действия продавца (как кнопки в боте)."""
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from api.admin.deps import CurrentStaff, Staff
from api.admin.schemas import AdminOrderOut, CustomerOut, DeliveryOut, OrderActionIn, OrderActionOut, OrderPage
from api.deps import DbSession, Notifications
from api.schemas import LocationOut, OrderStatusOut, ShopRef
from db.models import Order
from domain.enums import OrderStatus, Provider
from domain.messages import OutMessage, ToShopStaff, ToUser
from domain.order_flow import InvalidTransition, can_transition
from services import notifications, order_actions, orders, shops
from services.order_actions import StaffAction
from utils.escape import safe_html
from utils.logging_config import structured_logger

router = APIRouter(prefix="/orders", tags=["админка: заказы"])

StatusGroup = Literal["new", "work", "done", "declined", "all"]


def _actions(order: Order) -> list[StaffAction]:
    return [a for a, target in order_actions.TARGET.items() if can_transition(order.status_id, target)]


def _customer(order: Order) -> CustomerOut:
    user = order.user
    identities = {i.provider: i for i in user.identities}
    telegram, vk = identities.get(Provider.TELEGRAM), identities.get(Provider.VK)
    return CustomerOut(
        id=user.id, name=user.firstname, phone=user.phone_number,
        telegram_username=(telegram.username if telegram else None) or user.username,
        vk_url=f"https://vk.com/id{vk.external_id}" if vk else None,
    )


async def order_out(session, order: Order) -> AdminOrderOut:
    pickup = None
    if order.location is not None:
        point = await shops.location_point(session, order.location_id)
        pickup = LocationOut(
            id=order.location.id, name=order.location.name, address=order.location.address,
            opening_hours=order.location.opening_hours,
            latitude=point.latitude if point else None, longitude=point.longitude if point else None,
        )
    size = order.product_size
    return AdminOrderOut(
        id=order.id,
        status=OrderStatusOut(code=OrderStatus(order.status_id).name.lower(), title=order.status.name if order.status else ""),
        shop=ShopRef(id=order.shop.id, name=order.shop.name),
        product_name=size.product.name, size=f"{size.sizes.name}", quantity=order.product_count,
        total=order.total_price, comment=order.customer_comment or None,
        decline_reason=order.manager_comment if order.status_id == OrderStatus.DECLINED else None,
        created_at=order.created_at, updated_at=order.updated_at,
        customer=_customer(order),
        manager=(order.manager.firstname or order.manager.username) if order.manager else None,
        pickup=pickup, actions=_actions(order),
    )


async def _load(session, staff: Staff, order_id: int) -> Order:
    order = await orders.get_order(session, order_id)
    # чужой магазин — как будто заказа нет
    if order is None or order.status_id in (OrderStatus.DRAFT, OrderStatus.EXPIRED) or not staff.can_manage(order.shop_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Заказ не найден.")
    return order


@router.get("", response_model=OrderPage)
async def list_orders(
    staff: CurrentStaff,
    session: DbSession,
    group: StatusGroup = "all",
    shop_id: int | None = None,
    q: Annotated[str, Query(max_length=64)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    items, total = await orders.staff_orders(
        session, staff.shop_filter(shop_id), statuses=orders.STATUS_GROUPS.get(group), search=q,
        limit=limit, offset=offset,
    )
    return OrderPage(items=[await order_out(session, o) for o in items], total=total)


@router.get("/{order_id}", response_model=AdminOrderOut)
async def get_order(order_id: int, staff: CurrentStaff, session: DbSession) -> AdminOrderOut:
    return await order_out(session, await _load(session, staff, order_id))


@router.post("/{order_id}/actions", response_model=OrderActionOut)
async def act(
    order_id: int, body: OrderActionIn, staff: CurrentStaff, session: DbSession, notifier: Notifications,
) -> OrderActionOut:
    """Подтвердить / готов / выдан / отклонить — с теми же уведомлениями покупателю, что и в боте.

    В служебный чат магазина — короткая заметка, кто что сделал в админке (карточка там устарела).
    """
    order = await _load(session, staff, order_id)
    try:
        result = order_actions.apply(order, body.action, staff.user.id, body.reason)
    except InvalidTransition as exc:
        status_name = order.status.name if order.status else "—"
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"Заказ №{order.id} в статусе «{status_name}» — это действие недоступно.") from exc

    to_customer = [n for n in result.notices if isinstance(n[0], ToUser)]
    to_staff = [n for n in result.notices if not isinstance(n[0], ToUser)]
    if body.action != StaffAction.RECEIVED:   # о выдаче чат и так узнает из уведомлений
        who = safe_html(staff.user.firstname or staff.user.username or "менеджер")
        to_staff.append((ToShopStaff(order.shop_id), OutMessage(
            f"🖥 Заказ №{order.id} {order_actions.TITLES[body.action]} в админке ({who})."
            + (f"\nПричина: {safe_html(order.manager_comment)}" if body.action == StaffAction.DECLINE else "")
        ), "order_admin_action"))
    customer_ids = await notifications.enqueue_all(session, to_customer)
    staff_ids = await notifications.enqueue_all(session, to_staff)
    await session.commit()

    # итог отправки покупателю показываем продавцу — как приписку «не получил уведомление» в боте
    delivery = await notifier.deliver(customer_ids)
    await notifier.deliver(staff_ids)
    structured_logger.info(
        f"Order {body.action} in admin", user_id=staff.user.id, order_id=order.id, action=f"admin_order_{body.action}",
        context={"shop_id": order.shop_id, "minutes_in_status": order_actions.minutes(result.spent)},
    )
    order = await orders.get_order(session, order.id)
    return OrderActionOut(
        order=await order_out(session, order),
        customer_notified=DeliveryOut(sent=delivery.sent, queued=delivery.queued, failed=delivery.failed),
    )
