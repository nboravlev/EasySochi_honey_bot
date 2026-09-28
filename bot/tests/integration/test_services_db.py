from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from db.models import Image, Order, Product, Shop, TastingSignup, User
from domain.enums import OrderStatus as S
from domain.enums import Provider, Role, TastingStatus
from services import catalog, identity, shops, stats, tasting, users
from services.orders import (
    ProductUnavailable,
    create_draft,
    expire_stale_drafts,
    get_customer_draft,
    get_order,
    transition,
)
from utils.timeutils import utcnow

from .conftest import OTHER_SELLER_TG, SELLER_TG

pytestmark = pytest.mark.db


async def status_of(session, order_id) -> int:
    return await session.scalar(select(Order.status_id).where(Order.id == order_id))


# --- пользователи и платформы

async def test_identity_per_platform(session, world):
    same, created = await identity.get_or_create_user(session, Provider.TELEGRAM, SELLER_TG)
    assert not created and same.id == world.seller.id
    # тот же человек во VK — другой аккаунт платформы, пока не объединён: новый пользователь
    vk_user, created = await identity.get_or_create_user(session, Provider.VK, SELLER_TG)
    assert created and vk_user.id != world.seller.id
    assert await identity.external_id(session, world.seller.id, Provider.TELEGRAM) == str(SELLER_TG)
    assert await identity.external_id(session, world.seller.id, Provider.VK) is None


# --- заказы

async def test_draft_belongs_to_product_shop_and_pickup_point(session, world):
    order = await create_draft(session, world.buyer.id, world.own.id)
    assert order.shop_id == world.shop_a.id
    assert order.location_id == world.location_a.id
    other = await create_draft(session, world.buyer.id, world.other.id)
    assert other.shop_id == world.shop_b.id


async def test_new_draft_expires_previous_drafts(session, world):
    first = await create_draft(session, world.buyer.id, world.own.id)
    second = await create_draft(session, world.buyer.id, world.other.id)
    assert await status_of(session, first.id) == S.EXPIRED
    assert await status_of(session, second.id) == S.DRAFT
    # старая карточка черновика больше не принимает изменений, чужой — тоже
    assert await get_customer_draft(session, first.id, world.buyer.id) is None
    assert await get_customer_draft(session, second.id, world.seller.id) is None


async def test_draft_for_unavailable_product(session, world):
    await session.execute(update(Product).where(Product.id == world.own.product_id).values(is_active=False))
    with pytest.raises(ProductUnavailable):
        await create_draft(session, world.buyer.id, world.own.id)


async def test_full_lifecycle_with_timestamptz(session, world):
    draft = await create_draft(session, world.buyer.id, world.own.id)
    order = await get_order(session, draft.id)
    for target in (S.CREATED, S.PROCESSING, S.READY, S.CUSTOMER_NOTIFIED, S.RECEIVED):
        transition(order, target, actor_id=world.seller.id)
        await session.flush()
    stored = (await session.execute(
        select(Order.status_id, Order.manager_id, Order.created_at, Order.updated_at, Order.total_price)
        .where(Order.id == draft.id)
    )).one()
    assert stored.status_id == S.RECEIVED
    assert stored.manager_id == world.seller.id
    assert stored.created_at.tzinfo is not None and stored.updated_at.tzinfo is not None
    assert stored.total_price == Decimal("1500.00")


async def test_expire_stale_drafts_only_old_ones(session, world):
    old = await create_draft(session, world.buyer.id, world.own.id)
    await session.execute(update(Order).where(Order.id == old.id).values(updated_at=utcnow() - timedelta(hours=25)))
    fresh = await create_draft(session, world.seller.id, world.own.id)
    assert await expire_stale_drafts(session) >= 1
    assert await status_of(session, old.id) == S.EXPIRED
    assert await status_of(session, fresh.id) == S.DRAFT


async def test_customer_with_orders_cannot_be_deleted(session, world):
    await create_draft(session, world.buyer.id, world.own.id)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(delete(User).where(User.id == world.buyer.id))


async def test_shop_with_products_cannot_be_deleted(session, world):
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(delete(Shop).where(Shop.id == world.shop_b.id))


# --- каталог: магазины изолированы

async def test_catalog_scoping(session, world):
    type_ids_a = {t.id for t in await catalog.product_types(session, world.shop_a.id)}
    assert type_ids_a == {world.type_id}
    all_products = {p.id for p in await catalog.manager_products(session, None)}
    own_products = {p.id for p in await catalog.manager_products(session, world.shop_a.id)}
    assert world.other.product_id in all_products and world.other.product_id not in own_products
    # менеджер магазина A не видит и не может менять товар магазина B
    assert await catalog.get_offer(session, world.other.id, world.shop_a.id) is None
    assert await catalog.update_price(session, world.other.id, Decimal("1"), world.shop_a.id, world.seller.id) is None
    assert not await catalog.discard_draft(session, world.other.product_id, world.shop_a.id)
    result, _ = await catalog.withdraw(session, world.other.product_id, world.shop_a.id, world.seller.id)
    assert result is catalog.WithdrawResult.NOT_FOUND
    # а свой — может
    changed = await catalog.update_price(session, world.own.id, Decimal("1700"), world.shop_a.id, world.seller.id)
    assert changed is not None and changed[1] == Decimal("1500.00")


async def test_withdraw_blocked_by_active_orders(session, world):
    order = await create_draft(session, world.buyer.id, world.own.id)
    transition(order, S.CREATED)
    await session.flush()
    result, active = await catalog.withdraw(session, world.own.product_id, world.shop_a.id, world.seller.id)
    assert result is catalog.WithdrawResult.HAS_ACTIVE_ORDERS and active == [order.id]


async def test_create_and_publish_product_in_shop(session, world):
    product = await catalog.create_draft_product(
        session, shop_id=world.shop_b.id, author_id=world.other_seller.id, name="Новый", type_id=world.type_id,
        description="—", prices=[("0.5кг", Decimal("700")), ("1.0кг", Decimal("1300"))], photos=[catalog.Photo(None, "products/a.jpg", "file-1")],
    )
    assert product.shop_id == world.shop_b.id and product.is_draft
    assert await catalog.publish(session, product.id, world.shop_a.id) is None     # чужой магазин
    published = await catalog.publish(session, product.id, world.shop_b.id)
    assert published is not None and not published.is_draft
    assert [o.price for o in await catalog.offers(session, product.id)] == [Decimal("700.00"), Decimal("1300.00")]

    cover = await catalog.cover_image(session, product.id)
    assert (cover.storage_key, cover.tg_file_id) == ("products/a.jpg", "file-1")
    await catalog.remember_tg_file_id(session, cover.id, "file-2")
    assert (await catalog.cover_image(session, product.id)).tg_file_id == "file-2"


async def test_photos_without_storage(session, world):
    session.add_all([Image(product_id=world.own.product_id, tg_file_id="old-1"),
                     Image(product_id=world.own.product_id, storage_key="products/new.jpg")])
    await session.flush()
    legacy = [p for p in await catalog.photos_without_storage(session, limit=100) if p.tg_file_id == "old-1"]
    assert len(legacy) == 1
    await catalog.set_storage_key(session, legacy[0].id, "products/old-1.jpg")
    assert all(p.id != legacy[0].id for p in await catalog.photos_without_storage(session, limit=100))

    # фото без файла и без file_id — ошибка схемы
    session.add(Image(product_id=world.own.product_id))
    with pytest.raises(IntegrityError):
        await session.flush()


# --- статистика

async def make_order(session, world, product_size, status, count=1) -> Order:
    order = await create_draft(session, world.buyer.id, product_size.id)
    order.product_count = count
    order.total_price = product_size.price * count
    order.status_id = status
    await session.flush()
    return order


async def test_stats_per_shop(session, world):
    own = world.own
    await make_order(session, world, own, S.CREATED)                  # новый
    await make_order(session, world, own, S.PROCESSING, count=2)      # в работе
    await make_order(session, world, own, S.RECEIVED, count=3)        # выдан
    await make_order(session, world, own, S.DECLINED)
    await make_order(session, world, own, S.EXPIRED)                  # брошенная корзина
    await make_order(session, world, world.other, S.RECEIVED)         # магазин B
    await create_draft(session, world.buyer.id, own.id)               # черновик

    shop_a = await stats.collect(session, world.shop_a.id)
    assert (shop_a.new.count, shop_a.new.total) == (1, Decimal("1500.00"))
    assert (shop_a.in_progress.count, shop_a.in_progress.total) == (1, Decimal("3000.00"))
    assert (shop_a.completed.count, shop_a.completed.total) == (1, Decimal("4500.00"))
    assert shop_a.declined.count == 1 and shop_a.total.count == 3
    sold = {name: (kg, amount) for name, kg, amount in shop_a.sales_by_product}
    assert sold == {"Мёд own": (Decimal("5.0"), Decimal("7500.00"))}
    assert shop_a.shop_scoped and shop_a.active_users == 1            # покупатели магазина, не вся платформа
    assert "Покупателей: 1" in stats.format_stats(shop_a)

    everything = await stats.collect(session, None)                   # владелец платформы
    assert everything.completed.count == 2
    assert "Мёд other" in {name for name, _, _ in everything.sales_by_product}
    assert "Пользователей" in stats.format_stats(everything)


# --- дегустации по магазинам

async def test_tasting_signup_invite_and_rsvp_per_shop(session, world):
    record, created = await tasting.signup(session, world.shop_a.id, world.buyer.id)
    again, created_again = await tasting.signup(session, world.shop_a.id, world.buyer.id)
    assert created and not created_again and again.id == record.id
    await tasting.signup(session, world.shop_b.id, world.buyer.id)    # в другой магазин — отдельная запись
    await tasting.signup(session, world.shop_a.id, world.seller.id)

    event, invited = await tasting.invite_waiting(session, world.shop_a.id, utcnow() + timedelta(days=3),
                                                  created_by=world.seller.id)
    assert {r.user_id for r in invited} == {world.buyer.id, world.seller.id}
    assert await tasting.waiting_count(session, world.shop_a.id) == 0
    assert await tasting.waiting_count(session, world.shop_b.id) == 1   # лист B не тронут

    buyer_invite = next(r for r in invited if r.user_id == world.buyer.id)
    assert await tasting.respond(session, buyer_invite.id, world.seller.id, going=True) is None   # чужое
    assert (await tasting.respond(session, buyer_invite.id, world.buyer.id, going=True)).status == TastingStatus.GOING
    assert (await tasting.respond(session, buyer_invite.id, world.buyer.id, going=False)).status == TastingStatus.DECLINED

    summary = await tasting.next_event_summary(session, world.shop_a.id)
    assert summary.event.id == event.id and summary.invited == 2 and summary.declined == 1
    assert await tasting.next_event_summary(session, world.shop_b.id) is None


async def test_rsvp_after_event_is_rejected(session, world):
    await tasting.signup(session, world.shop_a.id, world.buyer.id)
    event, invited = await tasting.invite_waiting(session, world.shop_a.id, utcnow() + timedelta(days=1), created_by=None)
    event.starts_at = utcnow() - timedelta(hours=1)
    await session.flush()
    assert await tasting.respond(session, invited[0].id, world.buyer.id, going=True) is None


async def test_signup_status_constraint(session, world):
    session.add(TastingSignup(shop_id=world.shop_a.id, user_id=world.buyer.id, status="maybe"))
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.flush()


# --- магазины: служебные каналы

async def test_staff_channels_are_per_shop(session, world):
    await shops.set_staff_channel(session, world.shop_a.id, Provider.TELEGRAM, -1001)
    await shops.set_staff_channel(session, world.shop_b.id, Provider.TELEGRAM, -1002)
    assert await shops.shop_for_staff_channel(session, Provider.TELEGRAM, -1001) == world.shop_a.id
    assert await shops.shop_for_staff_channel(session, Provider.TELEGRAM, -1002) == world.shop_b.id
    assert await shops.staff_channel(session, world.shop_b.id, Provider.VK) is None
    await shops.set_staff_channel(session, world.shop_a.id, Provider.TELEGRAM, -1003)   # смена чата
    assert await shops.staff_channel(session, world.shop_a.id, Provider.TELEGRAM) == "-1003"


async def test_location_point(session, world):
    point = await shops.location_point(session, world.location_a.id)
    assert round(point.latitude, 4) == 43.6728 and round(point.longitude, 4) == 40.2001


# --- роли

async def test_bootstrap_managers_once(session, world):
    await session.execute(update(User).where(User.role_id == Role.MANAGER).values(role_id=Role.USER, shop_id=None))
    new_tg = 900099  # ещё не нажимал /start
    assert await users.bootstrap_managers(session, {SELLER_TG, new_tg}, world.shop_a.id) == 2
    managers = await users.list_managers(session, world.shop_a.id)
    assert {u.id for u in managers} >= {world.seller.id}
    newcomer = await identity.find_user(session, Provider.TELEGRAM, new_tg)
    assert newcomer.role_id == Role.MANAGER and newcomer.shop_id == world.shop_a.id
    assert await users.bootstrap_managers(session, {OTHER_SELLER_TG}, world.shop_a.id) == 0


async def test_find_and_set_manager(session, world):
    user = await users.find_user(session, "@Seller_Test")
    assert user.id == world.seller.id
    assert (await users.find_user(session, str(OTHER_SELLER_TG))).id == world.other_seller.id
    assert await users.find_user(session, "@nobody_here") is None

    await users.set_manager(session, user, world.shop_b.id)
    assert (user.role_id, user.shop_id) == (Role.MANAGER, world.shop_b.id)
    await users.set_manager(session, user, None)
    assert (user.role_id, user.shop_id) == (Role.USER, None)
