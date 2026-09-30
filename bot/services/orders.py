"""Операции с заказами. Все смены статуса — через transition(), который сверяется с domain.order_flow."""
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Order, ProductSize, Session, Size, User
from domain.enums import OrderStatus, Role
from domain.order_flow import check_transition
from services import shops
from utils.constants import DRAFT_TTL_HOURS, MAX_COMMENT_LENGTH, MAX_PRODUCT_COUNT
from utils.timeutils import utcnow

MAX_REASON_LENGTH = 255  # orders.manager_comment VARCHAR(255)
MAX_ORDERS_PER_HOUR = 10  # с сайта / Mini App; в боте заказ идёт через черновик по одному

# всё, что нужно для карточек заказа и уведомлений
ORDER_DETAILS = (
    selectinload(Order.product_size).selectinload(ProductSize.product),
    selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
    selectinload(Order.user).selectinload(User.identities),   # контакты покупателя в других платформах
    selectinload(Order.manager),
    selectinload(Order.status),
    selectinload(Order.session),
    selectinload(Order.shop),
    selectinload(Order.location),
)


class OrderError(Exception):
    """Ошибка, текст которой можно показать пользователю."""

    user_message = "Не удалось выполнить действие с заказом."

    def __init__(self, user_message: str | None = None):
        if user_message:
            self.user_message = user_message
        super().__init__(self.user_message)


class ProductUnavailable(OrderError):
    user_message = "❌ Этот товар больше не продаётся. Выберите другой: /honey_buy"


class QuantityLimit(OrderError):
    user_message = (
        f"Не больше {MAX_PRODUCT_COUNT} шт. в одном заказе. "
        "Для крупного заказа напишите продавцу через /help."
    )


class CommentTooLong(OrderError):
    def __init__(self, length: int):
        super().__init__(
            f"Комментарий слишком длинный ({length} символов). "
            f"Сократите до {MAX_COMMENT_LENGTH} и отправьте ещё раз:"
        )


class TooManyOrders(OrderError):
    user_message = "Слишком много заказов за час. Попробуйте позже или напишите продавцу."


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        # populate_existing: заказ, только что созданный в этой сессии, догружается со связями
        select(Order).options(*ORDER_DETAILS).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_customer_draft(session: AsyncSession, order_id: int, customer_id: int) -> Order | None:
    """Черновик покупателя или None, если заказ чужой или уже оформлен (старые кнопки не должны его менять)."""
    order = await get_order(session, order_id)
    if order is None or order.customer_id != customer_id or order.status_id != OrderStatus.DRAFT:
        return None
    return order


async def expire_user_drafts(session: AsyncSession, customer_id: int) -> int:
    """Закрывает прежние черновики покупателя: у него одновременно не больше одного."""
    result = await session.execute(
        update(Order)
        .where(Order.customer_id == customer_id, Order.status_id == OrderStatus.DRAFT)
        .values(status_id=OrderStatus.EXPIRED, updated_at=utcnow())
    )
    return result.rowcount


async def expire_stale_drafts(session: AsyncSession, older_than: timedelta = timedelta(hours=DRAFT_TTL_HOURS)) -> int:
    """Закрывает брошенные черновики (без уведомления покупателя)."""
    result = await session.execute(
        update(Order)
        .where(Order.status_id == OrderStatus.DRAFT, Order.updated_at < utcnow() - older_than)
        .values(status_id=OrderStatus.EXPIRED, updated_at=utcnow())
    )
    return result.rowcount


async def _available_size(session: AsyncSession, product_size_id: int) -> ProductSize:
    result = await session.execute(
        select(ProductSize)
        .options(
            selectinload(ProductSize.product),
            selectinload(ProductSize.sizes).selectinload(Size.package),
        )
        .where(ProductSize.id == product_size_id)
    )
    product_size = result.scalar_one_or_none()
    # кнопки размера остаются на старых карточках — товар мог быть снят с продажи
    if (product_size is None or not product_size.is_active
            or not product_size.product.is_active or product_size.product.is_draft):
        raise ProductUnavailable()
    return product_size


async def create_draft(session: AsyncSession, customer_id: int, product_size_id: int) -> Order:
    """Черновик заказа на 1 шт. выбранного размера в магазине этого товара.

    Точка выдачи — основная точка самовывоза магазина. Прежние черновики покупателя закрываются.
    """
    product_size = await _available_size(session, product_size_id)
    await expire_user_drafts(session, customer_id)

    # сессия покупки — журнал действий покупателя по заказу
    audit = Session(user_id=customer_id, role_id=Role.BUYER, last_action={"event": "order_started"})
    session.add(audit)
    await session.flush()

    location = await shops.pickup_location(session, product_size.product.shop_id)
    order = Order(
        customer_id=customer_id,
        shop_id=product_size.product.shop_id,
        location=location,
        product_size=product_size,
        status_id=OrderStatus.DRAFT,
        product_count=1,
        total_price=product_size.price,
        session_id=audit.id,
    )
    session.add(order)
    await session.flush()
    return order


async def place_order(
    session: AsyncSession,
    customer_id: int,
    product_size_id: int,
    quantity: int,
    comment: str = "",
    *,
    channel: str,
    shop_id: int | None = None,
) -> Order:
    """Оформить заказ сразу, без черновика (сайт / Mini App: покупатель всё выбрал на одном экране).

    Черновик в чате бота, если он есть, не трогаем. channel — откуда заказ (web, vk, …) для журнала.
    shop_id — магазин витрины: товар другого магазина заказать через неё нельзя (None — маркетплейс).
    Возвращает заказ со всеми связями — для карточки продавцу.
    """
    if not 1 <= quantity <= MAX_PRODUCT_COUNT:
        raise QuantityLimit()
    if await recent_orders_count(session, customer_id) >= MAX_ORDERS_PER_HOUR:
        raise TooManyOrders()
    product_size = await _available_size(session, product_size_id)
    if shop_id is not None and product_size.product.shop_id != shop_id:
        raise ProductUnavailable()

    audit = Session(user_id=customer_id, role_id=Role.BUYER, last_action={"event": "order_placed", "channel": channel})
    session.add(audit)
    await session.flush()
    order = Order(
        customer_id=customer_id,
        shop_id=product_size.product.shop_id,
        location=await shops.pickup_location(session, product_size.product.shop_id),
        product_size=product_size,
        status_id=OrderStatus.CREATED,
        product_count=quantity,
        total_price=product_size.price * quantity,
        session_id=audit.id,
    )
    set_comment(order, comment)
    session.add(order)
    await session.flush()
    return await get_order(session, order.id)


async def recent_orders_count(session: AsyncSession, customer_id: int, within: timedelta = timedelta(hours=1)) -> int:
    """Оформленные заказы покупателя за последний час — защита от накрутки заказов с сайта."""
    return await session.scalar(
        select(func.count(Order.id)).where(
            Order.customer_id == customer_id,
            Order.created_at > utcnow() - within,
            Order.status_id.not_in((OrderStatus.DRAFT, OrderStatus.EXPIRED)),
        )
    )


async def customer_orders(session: AsyncSession, customer_id: int, limit: int = 30) -> list[Order]:
    """Заказы покупателя, новые сверху (черновики и просроченные не показываем)."""
    result = await session.scalars(
        select(Order).options(*ORDER_DETAILS)
        .where(Order.customer_id == customer_id, Order.status_id.not_in((OrderStatus.DRAFT, OrderStatus.EXPIRED)))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return list(result.all())


def change_quantity(order: Order, delta: int) -> bool:
    """Меняет количество в черновике и пересчитывает сумму. False — если меньше 1 (ничего не изменилось)."""
    new_count = order.product_count + delta
    if new_count < 1:
        return False
    if new_count > MAX_PRODUCT_COUNT:
        raise QuantityLimit()
    order.product_count = new_count
    order.total_price = order.product_size.price * new_count
    return True


def set_comment(order: Order, text: str) -> None:
    text = text.strip()
    if len(text) > MAX_COMMENT_LENGTH:
        raise CommentTooLong(len(text))
    order.customer_comment = text


def transition(order: Order, target: OrderStatus, *, actor_id: int | None = None) -> timedelta:
    """Меняет статус заказа, если переход разрешён (иначе domain.order_flow.InvalidTransition).

    Возвращает, сколько заказ пробыл в прежнем статусе (для метрик в логах).
    """
    check_transition(order.status_id, target)
    now = utcnow()
    time_in_status = now - (order.updated_at or order.created_at or now)
    order.status_id = target
    order.updated_at = now
    if target == OrderStatus.PROCESSING:
        order.manager_id = actor_id
    return time_in_status


def decline(order: Order, reason: str, *, actor_id: int | None = None) -> timedelta:
    time_in_status = transition(order, OrderStatus.DECLINED, actor_id=actor_id)
    order.manager_comment = reason.strip()[:MAX_REASON_LENGTH] or "Причина не указана"
    return time_in_status
