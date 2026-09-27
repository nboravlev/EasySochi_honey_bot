from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from db.models import Order, Product, TastingSignup, User
from domain.enums import OrderStatus as S
from domain.enums import Role, TastingStatus
from services import stats, tasting, users
from services.orders import (
    ProductUnavailable,
    create_draft,
    expire_stale_drafts,
    get_customer_draft,
    get_order,
    transition,
)
from utils.timeutils import utcnow

from .conftest import BUYER_ID, OTHER_SELLER_ID, SELLER_ID

pytestmark = pytest.mark.db


async def status_of(session, order_id) -> int:
    return await session.scalar(select(Order.status_id).where(Order.id == order_id))


# --- заказы

async def test_new_draft_expires_previous_drafts(session, catalog):
    first = await create_draft(session, BUYER_ID, catalog["own"].id)
    second = await create_draft(session, BUYER_ID, catalog["other"].id)
    assert await status_of(session, first.id) == S.EXPIRED
    assert await status_of(session, second.id) == S.DRAFT
    # старая карточка черновика больше не принимает изменений
    assert await get_customer_draft(session, first.id, BUYER_ID) is None
    assert await get_customer_draft(session, second.id, OTHER_SELLER_ID) is None  # чужой


async def test_draft_for_unavailable_product(session, catalog):
    await session.execute(update(Product).where(Product.id == catalog["own"].product_id).values(is_active=False))
    with pytest.raises(ProductUnavailable):
        await create_draft(session, BUYER_ID, catalog["own"].id)


async def test_full_lifecycle_with_timestamptz(session, catalog):
    draft = await create_draft(session, BUYER_ID, catalog["own"].id)
    order = await get_order(session, draft.id)
    for target in (S.CREATED, S.PROCESSING, S.READY, S.CUSTOMER_NOTIFIED, S.RECEIVED):
        transition(order, target, actor_id=SELLER_ID)
        await session.flush()
    # читаем колонки прямо из БД, минуя объекты в identity map
    stored = (await session.execute(
        select(Order.status_id, Order.manager_id, Order.created_at, Order.updated_at, Order.total_price)
        .where(Order.id == draft.id)
    )).one()
    assert stored.status_id == S.RECEIVED
    assert stored.manager_id == SELLER_ID
    assert stored.created_at.tzinfo is not None and stored.updated_at.tzinfo is not None
    assert stored.total_price == Decimal("1500.00")


async def test_expire_stale_drafts_only_old_ones(session, catalog):
    old = await create_draft(session, BUYER_ID, catalog["own"].id)
    await session.execute(update(Order).where(Order.id == old.id).values(updated_at=utcnow() - timedelta(hours=25)))
    fresh = await create_draft(session, OTHER_SELLER_ID, catalog["own"].id)
    assert await expire_stale_drafts(session) >= 1
    assert await status_of(session, old.id) == S.EXPIRED
    assert await status_of(session, fresh.id) == S.DRAFT


async def test_user_with_orders_cannot_be_deleted(session, catalog):
    await create_draft(session, BUYER_ID, catalog["own"].id)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(delete(User).where(User.tg_user_id == BUYER_ID))


# --- статистика

async def make_order(session, product_size, status, count=1) -> Order:
    order = await create_draft(session, BUYER_ID, product_size.id)
    order.product_count = count
    order.total_price = product_size.price * count
    order.status_id = status
    await session.flush()
    return order


async def test_stats_ignore_drafts_and_split_statuses(session, catalog):
    own = catalog["own"]
    await make_order(session, own, S.CREATED)                  # новый
    await make_order(session, own, S.PROCESSING, count=2)      # в работе
    await make_order(session, own, S.RECEIVED, count=3)        # выдан
    await make_order(session, own, S.DECLINED)
    await make_order(session, own, S.EXPIRED)                  # брошенная корзина
    await make_order(session, catalog["other"], S.RECEIVED)    # чужой товар
    await create_draft(session, BUYER_ID, own.id)              # черновик

    own_stats = await stats.collect(session, seller_id=SELLER_ID)
    assert (own_stats.new.count, own_stats.new.total) == (1, Decimal("1500.00"))
    assert (own_stats.in_progress.count, own_stats.in_progress.total) == (1, Decimal("3000.00"))
    assert (own_stats.completed.count, own_stats.completed.total) == (1, Decimal("4500.00"))
    assert own_stats.declined.count == 1
    assert own_stats.total.count == 3                          # без черновиков, просроченных и отклонённых
    sold = {name: (kg, amount) for name, kg, amount in own_stats.sales_by_product}
    assert sold == {"Мёд own": (Decimal("5.0"), Decimal("7500.00"))}  # в работе + выдан, без «нового»

    all_stats = await stats.collect(session, seller_id=None)   # владелец видит всё
    assert all_stats.completed.count == own_stats.completed.count + 1
    assert "Мёд other" in {name for name, _, _ in all_stats.sales_by_product}
    assert "Заказы</b> всего" in stats.format_stats(all_stats)


# --- дегустации

async def test_tasting_signup_invite_and_rsvp(session, catalog):
    record, created = await tasting.signup(session, BUYER_ID)
    again, created_again = await tasting.signup(session, BUYER_ID)
    assert created and not created_again and again.id == record.id
    await tasting.signup(session, SELLER_ID)
    assert await tasting.waiting_count(session) >= 2

    event, invited = await tasting.invite_waiting(session, utcnow() + timedelta(days=3), created_by=SELLER_ID)
    assert {r.tg_user_id for r in invited} >= {BUYER_ID, SELLER_ID}
    assert await tasting.waiting_count(session) == 0

    buyer_invite = next(r for r in invited if r.tg_user_id == BUYER_ID)
    assert await tasting.respond(session, buyer_invite.id, SELLER_ID, going=True) is None   # чужое приглашение
    answered = await tasting.respond(session, buyer_invite.id, BUYER_ID, going=True)
    assert answered.status == TastingStatus.GOING
    changed = await tasting.respond(session, buyer_invite.id, BUYER_ID, going=False)       # передумал
    assert changed.status == TastingStatus.DECLINED

    summary = await tasting.next_event_summary(session)
    assert summary.event.id == event.id
    assert summary.invited >= 2 and summary.declined >= 1

    # после приглашения можно снова записаться в лист ожидания
    _, created_new = await tasting.signup(session, BUYER_ID)
    assert created_new


async def test_rsvp_after_event_is_rejected(session, catalog):
    await tasting.signup(session, BUYER_ID)
    event, invited = await tasting.invite_waiting(session, utcnow() + timedelta(days=1), created_by=None)
    event.starts_at = utcnow() - timedelta(hours=1)
    await session.flush()
    record = next(r for r in invited if r.tg_user_id == BUYER_ID)
    assert await tasting.respond(session, record.id, BUYER_ID, going=True) is None


async def test_signup_status_constraint(session, catalog):
    session.add(TastingSignup(tg_user_id=BUYER_ID, status="maybe"))
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.flush()


# --- роли

async def test_bootstrap_managers_once(session, catalog):
    await session.execute(update(User).where(User.role_id == Role.MANAGER).values(role_id=Role.USER))
    new_manager_id = 900099  # ещё не нажимал /start
    assert await users.bootstrap_managers(session, {SELLER_ID, new_manager_id}) == 2
    managers = {u.tg_user_id for u in await users.list_managers(session)}
    assert managers == {SELLER_ID, new_manager_id}
    # повторный запуск: менеджеры уже есть — .env больше не применяется
    assert await users.bootstrap_managers(session, {OTHER_SELLER_ID}) == 0


async def test_find_and_set_manager(session, catalog):
    user = await users.find_user(session, "@Seller_Test")
    assert user.tg_user_id == SELLER_ID
    assert (await users.find_user(session, str(OTHER_SELLER_ID))).tg_user_id == OTHER_SELLER_ID
    assert await users.find_user(session, "@nobody_here") is None

    await users.set_manager(session, user, True)
    assert user.role_id == Role.MANAGER
    await users.set_manager(session, user, False)
    assert user.role_id == Role.USER
