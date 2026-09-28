"""Каталог: сорта, товары, размеры с ценами; управление карточками товаров магазина.

Параметр shop_id везде задаёт область видимости: id магазина — только его товары,
None — все магазины (общий каталог для покупателя или владелец платформы).
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Image, Order, Product, ProductSize, ProductType, Size
from domain.order_flow import ACTIVE_STATUSES
from utils.timeutils import utcnow


@dataclass(frozen=True)
class Offer:
    """Размер товара с ценой — то, что покупатель выбирает кнопкой."""
    product_size_id: int
    size_name: Decimal
    price: Decimal


@dataclass(frozen=True)
class Photo:
    """Фото товара: файл в хранилище (storage_key) и/или кэш Telegram (tg_file_id)."""
    id: int | None
    storage_key: str | None
    tg_file_id: str | None = None


class WithdrawResult(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    HAS_ACTIVE_ORDERS = "has_active_orders"


def _scoped(stmt, shop_id: int | None):
    return stmt if shop_id is None else stmt.where(Product.shop_id == shop_id)


def _published():
    return (Product.is_active.is_(True), Product.is_draft.is_(False))


# --- витрина покупателя

async def product_types(session: AsyncSession, shop_id: int | None) -> list[ProductType]:
    """Сорта, в которых сейчас есть товары в продаже (пустые сорта покупателю не показываем)."""
    stmt = (
        select(ProductType).join(Product, Product.type_id == ProductType.id)
        .where(*_published()).distinct().order_by(ProductType.name)
    )
    return list((await session.scalars(_scoped(stmt, shop_id))).all())


async def get_type(session: AsyncSession, type_id: int) -> ProductType | None:
    return await session.get(ProductType, type_id)


async def all_types(session: AsyncSession) -> list[ProductType]:
    """Все сорта — для создания карточки."""
    return list((await session.scalars(select(ProductType).order_by(ProductType.name))).all())


async def products_of_type(session: AsyncSession, type_id: int, shop_id: int | None) -> list[Product]:
    stmt = select(Product).where(Product.type_id == type_id, *_published()).order_by(Product.created_at)
    return list((await session.scalars(_scoped(stmt, shop_id))).all())


async def offers(session: AsyncSession, product_id: int) -> list[Offer]:
    rows = await session.execute(
        select(ProductSize.id, Size.name, ProductSize.price)
        .join(Size, Size.id == ProductSize.size_id)
        .where(ProductSize.product_id == product_id, ProductSize.is_active.is_(True))
        .order_by(ProductSize.price)
    )
    return [Offer(product_size_id=r[0], size_name=r[1], price=r[2]) for r in rows]


async def cover_image(session: AsyncSession, product_id: int) -> Photo | None:
    """Первое активное фото товара."""
    image = await session.scalar(
        select(Image)
        .where(Image.product_id == product_id, Image.is_active.is_(True))
        .order_by(Image.created_at, Image.id).limit(1)
    )
    return _photo(image) if image else None


def _photo(image: Image) -> Photo:
    return Photo(id=image.id, storage_key=image.storage_key, tg_file_id=image.tg_file_id)


def first_photo(product: Product) -> Photo | None:
    """Обложка уже загруженного товара (с images)."""
    images = sorted((i for i in product.images if i.is_active), key=lambda i: i.id)
    return _photo(images[0]) if images else None


async def remember_tg_file_id(session: AsyncSession, image_id: int, file_id: str) -> None:
    """Кэш Telegram: следующая отправка фото — по file_id, без загрузки файла."""
    await session.execute(update(Image).where(Image.id == image_id).values(tg_file_id=file_id))


async def photos_without_storage(session: AsyncSession, limit: int = 20, after_id: int = 0) -> list[Photo]:
    """Старые фото, которые есть только в Telegram (для переноса в своё хранилище)."""
    rows = await session.scalars(
        select(Image).where(Image.storage_key.is_(None), Image.id > after_id).order_by(Image.id).limit(limit)
    )
    return [_photo(image) for image in rows]


async def set_storage_key(session: AsyncSession, image_id: int, key: str) -> None:
    await session.execute(update(Image).where(Image.id == image_id).values(storage_key=key))


# --- кабинет менеджера

async def manager_products(session: AsyncSession, shop_id: int | None) -> list[Product]:
    stmt = (
        select(Product)
        .options(selectinload(Product.product_sizes).selectinload(ProductSize.sizes),
                 selectinload(Product.product_type))
        .where(*_published()).order_by(Product.created_at)
    )
    return list((await session.scalars(_scoped(stmt, shop_id))).all())


async def get_product(session: AsyncSession, product_id: int, shop_id: int | None) -> Product | None:
    """Товар, если он в области видимости (чужой магазин — как будто товара нет)."""
    stmt = (
        select(Product)
        .options(selectinload(Product.product_sizes).selectinload(ProductSize.sizes),
                 selectinload(Product.images), selectinload(Product.product_type))
        .where(Product.id == product_id)
    )
    return await session.scalar(_scoped(stmt, shop_id))


async def size_id_by_label(session: AsyncSession, label: str) -> int | None:
    """«0.5кг» → id размера."""
    value = Decimal(label.replace("кг", "").replace(",", ".").strip())
    return await session.scalar(select(Size.id).where(Size.name == value))


async def create_draft_product(
    session: AsyncSession,
    *,
    shop_id: int,
    author_id: int | None,
    name: str,
    type_id: int,
    description: str,
    prices: list[tuple[str, Decimal]],
    photos: list[Photo],
) -> Product:
    """Черновик карточки: публикуется отдельно (publish). prices — [(«0.5кг», цена), …]."""
    product = Product(shop_id=shop_id, created_by=author_id, name=name, type_id=type_id, description=description)
    session.add(product)
    await session.flush()
    for photo in photos:
        session.add(Image(product_id=product.id, storage_key=photo.storage_key, tg_file_id=photo.tg_file_id))
    for label, price in prices:
        size_id = await size_id_by_label(session, label)
        if size_id is None:
            raise LookupError(f"Размер {label!r} не найден в справочнике sizes")
        session.add(ProductSize(product_id=product.id, size_id=size_id, price=price))
    await session.flush()
    return await get_product(session, product.id, shop_id)


async def publish(session: AsyncSession, product_id: int, shop_id: int | None) -> Product | None:
    """Опубликовать черновик; удалённую карточку не воскрешаем."""
    product = await get_product(session, product_id, shop_id)
    if product is None or not product.is_active:
        return None
    product.is_draft = False
    await session.flush()
    return product


async def discard_draft(session: AsyncSession, product_id: int, shop_id: int | None) -> bool:
    """«Внести заново»: карточка и её размеры больше не показываются."""
    result = await session.execute(
        _scoped(update(Product).where(Product.id == product_id), shop_id).values(is_draft=True, is_active=False)
    )
    if result.rowcount == 0:
        return False
    await session.execute(
        update(ProductSize).where(ProductSize.product_id == product_id).values(is_active=False)
    )
    return True


async def withdraw(
    session: AsyncSession, product_id: int, shop_id: int | None, actor_id: int | None
) -> tuple[WithdrawResult, list[int]]:
    """Снять с продажи. Нельзя, пока у товара есть незавершённые заказы — возвращает их id."""
    product = await get_product(session, product_id, shop_id)
    if product is None:
        return WithdrawResult.NOT_FOUND, []
    active = list((await session.scalars(
        select(Order.id).join(ProductSize, ProductSize.id == Order.product_size_id)
        .where(ProductSize.product_id == product_id, Order.status_id.in_(ACTIVE_STATUSES))
    )).all())
    if active:
        return WithdrawResult.HAS_ACTIVE_ORDERS, active
    product.is_active = False
    product.updated_at = utcnow()
    product.updated_by = actor_id
    await session.flush()
    return WithdrawResult.OK, []


async def get_offer(session: AsyncSession, product_size_id: int, shop_id: int | None) -> ProductSize | None:
    """Размер товара для правки цены — если товар в области видимости."""
    stmt = (
        select(ProductSize)
        .options(selectinload(ProductSize.product), selectinload(ProductSize.sizes))
        .join(Product, Product.id == ProductSize.product_id)
        .where(ProductSize.id == product_size_id)
    )
    return await session.scalar(_scoped(stmt, shop_id))


async def update_price(
    session: AsyncSession, product_size_id: int, price: Decimal, shop_id: int | None, actor_id: int | None
) -> tuple[ProductSize, Decimal] | None:
    """Новая цена размера. Возвращает (размер, старая цена) или None, если размер вне области видимости."""
    offer = await get_offer(session, product_size_id, shop_id)
    if offer is None:
        return None
    old_price = offer.price
    offer.price = price
    offer.updated_at = utcnow()
    offer.product.updated_by = actor_id
    await session.flush()
    return offer, old_price
