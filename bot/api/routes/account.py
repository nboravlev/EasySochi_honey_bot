"""Покупатель: профиль, оформление заказа и «Мои заказы». Нужен вход через Telegram (initData)."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, DbSession, Notifications
from api.schemas import LocationOut, MeOut, MeUpdate, OrderCreate, OrderOut, OrderStatusOut, ShopRef
from db.models import Order, User
from domain.enums import OrderStatus
from domain.messages import ToShopStaff, ToUser
from services import notifications, order_notices, orders, shops
from utils.constants import MAX_PRODUCT_COUNT
from utils.logging_config import structured_logger
from utils.delivery import log_no_channel

CHANNEL = "webapp"

# тексты ошибок для витрины (у бота свои — с командами бота)
ORDER_ERRORS: dict[type[orders.OrderError], tuple[int, str]] = {
    orders.ProductUnavailable: (status.HTTP_409_CONFLICT, "Этот товар больше не продаётся. Обновите каталог."),
    orders.QuantityLimit: (status.HTTP_422_UNPROCESSABLE_ENTITY, f"Не больше {MAX_PRODUCT_COUNT} шт. в одном заказе."),
    orders.CommentTooLong: (status.HTTP_422_UNPROCESSABLE_ENTITY, "Комментарий слишком длинный."),
    orders.TooManyOrders: (status.HTTP_429_TOO_MANY_REQUESTS, orders.TooManyOrders.user_message),
}

router = APIRouter(tags=["покупатель"])


def me_out(user: User) -> MeOut:
    return MeOut(id=user.id, first_name=user.firstname, phone=user.phone_number)


@router.get("/me", response_model=MeOut)
async def get_me(user: CurrentUser) -> MeOut:
    return me_out(user)


@router.patch("/me", response_model=MeOut)
async def update_me(body: MeUpdate, user: CurrentUser, session: DbSession) -> MeOut:
    if body.first_name is not None:
        user.firstname = body.first_name.strip()
    if body.phone is not None:
        user.phone_number = body.phone.strip() or None
    await session.commit()
    return me_out(user)


async def order_out(session: AsyncSession, order: Order, points: dict[int, object] | None = None) -> OrderOut:
    points = {} if points is None else points
    pickup = None
    if order.location is not None:
        if order.location_id not in points:
            points[order.location_id] = await shops.location_point(session, order.location_id)
        point = points[order.location_id]
        pickup = LocationOut(
            id=order.location.id, name=order.location.name, address=order.location.address,
            opening_hours=order.location.opening_hours,
            latitude=point.latitude if point else None, longitude=point.longitude if point else None,
        )
    size = order.product_size
    return OrderOut(
        id=order.id,
        status=OrderStatusOut(code=OrderStatus(order.status_id).name.lower(),
                              title=order.status.name if order.status else ""),
        product_name=size.product.name,
        size=f"{size.sizes.name}",
        quantity=order.product_count,
        total=order.total_price,
        comment=order.customer_comment or None,
        decline_reason=order.manager_comment if order.status_id == OrderStatus.DECLINED else None,
        created_at=order.created_at,
        pickup=pickup,
        shop=ShopRef(id=order.shop.id, name=order.shop.name),
    )


@router.get("/orders", response_model=list[OrderOut])
async def my_orders(user: CurrentUser, session: DbSession) -> list[OrderOut]:
    points: dict[int, object] = {}
    return [await order_out(session, order, points) for order in await orders.customer_orders(session, user.id)]


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    background: BackgroundTasks,
    user: CurrentUser,
    session: DbSession,
    notifier: Notifications,
) -> OrderOut:
    """Оформить заказ (самовывоз). Продавцу — карточка в служебный чат, покупателю — сообщение в чат бота;
    дальше статусы приходят туда же, как при заказе через бота."""
    try:
        order = await orders.place_order(
            session, user.id, body.product_size_id, body.quantity, body.comment,
            channel=CHANNEL, shop_id=await shops.storefront_shop_id(session),
        )
    except orders.OrderError as exc:
        code, message = ORDER_ERRORS.get(type(exc), (status.HTTP_409_CONFLICT, exc.user_message))
        raise HTTPException(code, detail=message) from exc

    staff = await notifications.enqueue(
        session, ToShopStaff(order.shop_id), order_notices.new_order_for_staff(order), "order_created"
    )
    customer = await notifications.enqueue(
        session, ToUser(user.id), order_notices.order_placed_for_customer(order), "order_placed"
    )
    await session.commit()
    if not staff:
        log_no_channel(ToShopStaff(order.shop_id), "order_created")
    background.add_task(notifier.deliver, notifications.ids_of(staff + customer))

    structured_logger.info(
        "new order", user_id=user.id, order_id=order.id, action="order_created",
        context={"channel": CHANNEL, "item": order.product_size.product.name, "size": order.product_size.sizes.name,
                 "qty": order.product_count, "amount": order.total_price, "shop_id": order.shop_id},
    )
    return await order_out(session, order)
