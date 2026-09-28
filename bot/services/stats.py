"""Статистика для меню менеджера. Менеджер видит свои товары, владелец — все."""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Order, Product, ProductSize, Size, User
from domain.enums import OrderStatus
from services import tasting
from services.order_texts import rub
from utils.escape import safe_html
from utils.timeutils import format_local

# продажа состоялась или продавец её подтвердил
SOLD_STATUSES = (OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.CUSTOMER_NOTIFIED, OrderStatus.RECEIVED)
IN_PROGRESS_STATUSES = (OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.CUSTOMER_NOTIFIED)
# черновики и просроченные — не заказы, а брошенные корзины
NOT_ORDERS = (OrderStatus.DRAFT, OrderStatus.EXPIRED)


@dataclass
class Bucket:
    count: int = 0
    total: Decimal = Decimal(0)

    def add(self, count: int, total: Decimal | None) -> None:
        self.count += count
        self.total += total or Decimal(0)


@dataclass
class ManagerStats:
    sales_by_product: list[tuple[str, Decimal, Decimal]]  # название, кг, ₽
    new: Bucket = field(default_factory=Bucket)
    in_progress: Bucket = field(default_factory=Bucket)
    completed: Bucket = field(default_factory=Bucket)
    declined: Bucket = field(default_factory=Bucket)
    active_users: int = 0
    shop_scoped: bool = False
    tasting_waiting: int = 0
    next_tasting: tasting.EventSummary | None = None

    @property
    def total(self) -> Bucket:
        result = Bucket()
        for bucket in (self.new, self.in_progress, self.completed):
            result.add(bucket.count, bucket.total)
        return result


def _in_shop(stmt: Select, shop_id: int | None) -> Select:
    return stmt if shop_id is None else stmt.where(Order.shop_id == shop_id)


async def collect(session: AsyncSession, shop_id: int | None) -> ManagerStats:
    """Статистика магазина; shop_id=None — по всем магазинам (владелец платформы)."""
    kg = func.sum(Order.product_count * Size.name)
    sales_stmt = (
        select(Product.name, kg, func.sum(Order.total_price))
        .select_from(Order)
        .join(ProductSize, Order.product_size_id == ProductSize.id)
        .join(Product, ProductSize.product_id == Product.id)
        .join(Size, ProductSize.size_id == Size.id)
        .where(Order.status_id.in_(SOLD_STATUSES))
        .group_by(Product.name)
        .order_by(kg.desc())
    )
    sales = await session.execute(_in_shop(sales_stmt, shop_id))
    stats = ManagerStats(sales_by_product=[(name, kg or Decimal(0), total or Decimal(0)) for name, kg, total in sales])

    by_status = await session.execute(
        _in_shop(select(Order.status_id, func.count(Order.id), func.sum(Order.total_price)), shop_id)
        .where(Order.status_id.not_in(NOT_ORDERS))
        .group_by(Order.status_id)
    )
    for status_id, count, total in by_status:
        if status_id == OrderStatus.CREATED:
            stats.new.add(count, total)
        elif status_id in IN_PROGRESS_STATUSES:
            stats.in_progress.add(count, total)
        elif status_id == OrderStatus.RECEIVED:
            stats.completed.add(count, total)
        elif status_id == OrderStatus.DECLINED:
            stats.declined.add(count, total)

    if shop_id is None:
        stats.active_users = await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    else:
        # менеджер видит своих покупателей, а не всю аудиторию платформы
        stats.shop_scoped = True
        stats.active_users = await session.scalar(
            select(func.count(func.distinct(Order.customer_id)))
            .where(Order.shop_id == shop_id, Order.status_id.not_in(NOT_ORDERS))
        ) or 0
    stats.tasting_waiting = await tasting.waiting_count(session, shop_id)
    stats.next_tasting = await tasting.next_event_summary(session, shop_id)
    return stats


def format_stats(stats: ManagerStats) -> str:
    lines = ["📊 <b>Общая статистика продаж</b>\n", "<b>🍯 Подтверждённые и выданные заказы:</b>"]
    total_kg, total_sum = Decimal(0), Decimal(0)
    for name, kg, amount in stats.sales_by_product:
        lines.append(f"{safe_html(name)}: {kg:.1f}кг | {rub(amount)}")
        total_kg += kg
        total_sum += amount
    if not stats.sales_by_product:
        lines.append("пока нет")
    lines.append(f"\n<b>Итого:</b> {total_kg:.1f} кг | {rub(total_sum)}\n")

    total = stats.total
    lines += [
        f"📦 <b>Заказы</b> всего: {total.count} | {rub(total.total)}",
        f"✅ Выдано: {stats.completed.count} | {rub(stats.completed.total)}",
        f"🕓 В работе: {stats.in_progress.count} | {rub(stats.in_progress.total)}",
        f"🚨 <b>Новые: {stats.new.count} | {rub(stats.new.total)}</b>",
        f"❌ Отклонено: {stats.declined.count}\n",
        f"👨 {'Покупателей' if stats.shop_scoped else 'Пользователей'}: {stats.active_users}",
        f"🍽 Ждут приглашения на дегустацию: {stats.tasting_waiting}",
    ]
    if stats.next_tasting:
        event = stats.next_tasting
        lines.append(
            f"📅 Дегустация {format_local(event.event.starts_at, '%d.%m %H:%M')}: "
            f"придут {event.going}, не смогут {event.declined}, приглашено {event.invited}"
        )
    return "\n".join(lines)


async def manager_stats_message(session: AsyncSession, shop_id: int | None) -> str:
    return format_stats(await collect(session, shop_id))
