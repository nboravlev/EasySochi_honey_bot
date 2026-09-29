"""Магазины (тенанты): витрина, точки, служебные каналы."""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Shop, ShopChannel, ShopLocation
from domain.enums import Provider

STAFF = "staff"


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float


async def get_shop(session: AsyncSession, shop_id: int) -> Shop | None:
    return await session.get(Shop, shop_id)


async def get_by_slug(session: AsyncSession, slug: str) -> Shop | None:
    return await session.scalar(select(Shop).where(Shop.slug == slug))


async def storefront_shop_id(session: AsyncSession) -> int | None:
    """Магазин, чью витрину показывает бот (STOREFRONT_SHOP). None — общий каталог всех магазинов."""
    slug = get_settings().storefront_shop
    if not slug:
        return None
    shop = await get_by_slug(session, slug)
    if shop is None:
        raise RuntimeError(f"STOREFRONT_SHOP={slug!r}: такого магазина нет в БД")
    return shop.id


async def pickup_location(session: AsyncSession, shop_id: int) -> ShopLocation | None:
    """Основная точка самовывоза магазина (первая активная)."""
    return await session.scalar(
        select(ShopLocation)
        .where(ShopLocation.shop_id == shop_id, ShopLocation.is_active.is_(True), ShopLocation.is_pickup.is_(True))
        .order_by(ShopLocation.id).limit(1)
    )


async def active_locations(session: AsyncSession, shop_id: int) -> list[tuple[ShopLocation, Point | None]]:
    """Действующие точки магазина с координатами (для карты на витрине)."""
    rows = await session.execute(
        select(ShopLocation, func.ST_Y(ShopLocation.point), func.ST_X(ShopLocation.point))
        .where(ShopLocation.shop_id == shop_id, ShopLocation.is_active.is_(True))
        .order_by(ShopLocation.id)
    )
    return [(loc, Point(latitude=lat, longitude=lon) if lat is not None else None) for loc, lat, lon in rows.all()]


async def location_point(session: AsyncSession, location_id: int) -> Point | None:
    row = (await session.execute(
        select(func.ST_Y(ShopLocation.point), func.ST_X(ShopLocation.point))
        .where(ShopLocation.id == location_id, ShopLocation.point.is_not(None))
    )).first()
    return Point(latitude=row[0], longitude=row[1]) if row else None


async def staff_channel(session: AsyncSession, shop_id: int, provider: Provider) -> str | None:
    """Куда в платформе слать служебные уведомления магазина (например, ID Telegram-группы продавцов)."""
    return await session.scalar(
        select(ShopChannel.address).where(
            ShopChannel.shop_id == shop_id, ShopChannel.provider == provider, ShopChannel.purpose == STAFF
        )
    )


async def shop_for_staff_channel(session: AsyncSession, provider: Provider, address: str | int) -> int | None:
    """Магазин, чей служебный чат — это (например, нажатие кнопки в группе продавцов)."""
    return await session.scalar(
        select(ShopChannel.shop_id).where(
            ShopChannel.provider == provider, ShopChannel.address == str(address), ShopChannel.purpose == STAFF
        )
    )


async def set_staff_channel(session: AsyncSession, shop_id: int, provider: Provider, address: str | int) -> None:
    channel = await session.scalar(
        select(ShopChannel).where(
            ShopChannel.shop_id == shop_id, ShopChannel.provider == provider, ShopChannel.purpose == STAFF
        )
    )
    if channel is None:
        session.add(ShopChannel(shop_id=shop_id, provider=provider, address=str(address), purpose=STAFF))
    else:
        channel.address = str(address)
    await session.flush()


async def bootstrap_storefront(session: AsyncSession, admin_chat_id: int | None, seller_contact: str | None) -> list[str]:
    """Первый запуск после миграции: служебный чат и телефон витрины — из ADMIN_CHAT_ID / SELLER_CONTACT.

    Уже заполненное не трогает. Возвращает список того, что было заполнено.
    """
    shop_id = await storefront_shop_id(session)
    if shop_id is None:
        return []
    shop = await get_shop(session, shop_id)
    filled = []
    if admin_chat_id and await staff_channel(session, shop_id, Provider.TELEGRAM) is None:
        await set_staff_channel(session, shop_id, Provider.TELEGRAM, admin_chat_id)
        filled.append("telegram_staff_chat")
    if seller_contact and not shop.contact_phone:
        shop.contact_phone = seller_contact
        filled.append("contact_phone")
    await session.flush()
    return filled
