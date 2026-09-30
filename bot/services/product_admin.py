"""Карточки товаров в админке: все состояния (черновик / в продаже / снят), правка, цены, фото.

Бот создаёт карточку пошагово (services.catalog.create_draft_product), админка — формой; хранится одинаково.
shop_id — область видимости, как в catalog: id магазина менеджера или None у владельца платформы.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from db.models import Image, Product, ProductSize, ProductType, Size
from utils.constants import MAX_PRICE, MAX_PRODUCT_NAME_LENGTH
from utils.timeutils import utcnow

MAX_DESCRIPTION_LENGTH = 2000
MAX_PHOTOS = 10

DRAFT, PUBLISHED, WITHDRAWN = "draft", "published", "withdrawn"


class ProductError(ValueError):
    """Ошибка данных карточки — текст можно показать пользователю."""


def state(product: Product) -> str:
    if not product.is_active:
        return WITHDRAWN
    return DRAFT if product.is_draft else PUBLISHED


def _full(stmt):
    return stmt.options(
        selectinload(Product.product_sizes).selectinload(ProductSize.sizes).noload(Size.product_sizes),
        selectinload(Product.images), selectinload(Product.product_type), selectinload(Product.shop),
    )


async def list_products(session: AsyncSession, shop_id: int | None) -> list[Product]:
    """Все карточки магазина: в продаже и черновики сверху, снятые — внизу."""
    stmt = _full(select(Product)).order_by(Product.is_active.desc(), Product.created_at.desc(), Product.id.desc())
    if shop_id is not None:
        stmt = stmt.where(Product.shop_id == shop_id)
    return list((await session.scalars(stmt)).all())


async def get(session: AsyncSession, product_id: int, shop_id: int | None) -> Product | None:
    stmt = _full(select(Product)).where(Product.id == product_id).execution_options(populate_existing=True)
    if shop_id is not None:
        stmt = stmt.where(Product.shop_id == shop_id)
    return await session.scalar(stmt)


async def sizes(session: AsyncSession) -> list[Size]:
    # noload: у Size.product_sizes lazy="selectin" — иначе вместе со справочником загрузились бы все цены
    stmt = select(Size).options(selectinload(Size.package), noload(Size.product_sizes)).order_by(Size.name)
    return list((await session.scalars(stmt)).all())


async def types(session: AsyncSession) -> list[ProductType]:
    return list((await session.scalars(select(ProductType).order_by(ProductType.name))).all())


async def create_type(session: AsyncSession, name: str) -> ProductType:
    name = name.strip()
    if not name:
        raise ProductError("Укажите название сорта.")
    if await session.scalar(select(ProductType).where(ProductType.name == name)):
        raise ProductError(f"Сорт «{name}» уже есть.")
    product_type = ProductType(name=name)
    session.add(product_type)
    await session.flush()
    return product_type


def _check_texts(name: str | None, description: str | None) -> None:
    if name is not None and not name.strip():
        raise ProductError("Укажите название.")
    if name is not None and len(name.strip()) > MAX_PRODUCT_NAME_LENGTH:
        raise ProductError(f"Название — не длиннее {MAX_PRODUCT_NAME_LENGTH} символов.")
    if description is not None and len(description) > MAX_DESCRIPTION_LENGTH:
        raise ProductError(f"Описание — не длиннее {MAX_DESCRIPTION_LENGTH} символов.")


async def _check_type(session: AsyncSession, type_id: int) -> None:
    if await session.get(ProductType, type_id) is None:
        raise ProductError("Такого сорта нет.")


async def create(
    session: AsyncSession, *, shop_id: int, author_id: int | None, name: str, type_id: int, description: str,
    offers: list[tuple[int, Decimal]],
) -> Product:
    """Новая карточка — черновик; в продажу — publish."""
    _check_texts(name, description)
    await _check_type(session, type_id)
    product = Product(shop_id=shop_id, created_by=author_id, updated_by=author_id, name=name.strip(),
                      type_id=type_id, description=description.strip() or None, is_draft=True, is_active=True)
    session.add(product)
    await session.flush()
    await set_offers(session, product, [(size_id, price, True) for size_id, price in offers], author_id, fresh=True)
    return await get(session, product.id, None)


async def update(
    session: AsyncSession, product: Product, actor_id: int | None, *,
    name: str | None = None, type_id: int | None = None, description: str | None = None,
) -> None:
    _check_texts(name, description)
    if name is not None:
        product.name = name.strip()
    if type_id is not None:
        await _check_type(session, type_id)
        product.type_id = type_id
    if description is not None:
        product.description = description.strip() or None
    product.updated_by = actor_id
    product.updated_at = utcnow()
    await session.flush()


async def set_offers(
    session: AsyncSession, product: Product, offers: list[tuple[int, Decimal, bool]], actor_id: int | None,
    *, fresh: bool = False,
) -> None:
    """Цены по размерам целиком: перечисленные размеры — с этими ценами, остальные снимаются с продажи.

    Строки product_sizes не удаляются — на них ссылаются заказы.
    """
    if not any(active for _, _, active in offers):
        raise ProductError("Нужен хотя бы один размер в продаже.")
    known = set(await session.scalars(select(Size.id)))
    seen: set[int] = set()
    for size_id, price, _ in offers:
        if size_id not in known:
            raise ProductError("Такого размера нет.")
        if size_id in seen:
            raise ProductError("Размер указан дважды.")
        seen.add(size_id)
        if not (0 < price <= MAX_PRICE):
            raise ProductError(f"Цена — от 1 до {MAX_PRICE:,} ₽.".replace(",", " "))

    existing = {} if fresh else {ps.size_id: ps for ps in product.product_sizes}
    now = utcnow()
    for size_id, price, active in offers:
        row = existing.pop(size_id, None)
        if row is None:
            session.add(ProductSize(product_id=product.id, size_id=size_id, price=price, is_active=active))
        else:
            row.price, row.is_active, row.updated_at = price, active, now
    for row in existing.values():
        row.is_active = False
    product.updated_by = actor_id
    product.updated_at = now
    await session.flush()


async def add_photo(session: AsyncSession, product: Product, storage_key: str) -> Image:
    if sum(1 for i in product.images if i.is_active) >= MAX_PHOTOS:
        raise ProductError(f"Не больше {MAX_PHOTOS} фото у товара.")
    image = Image(product_id=product.id, storage_key=storage_key, is_active=True)
    session.add(image)
    await session.flush()
    return image


async def remove_photo(session: AsyncSession, product: Product, image_id: int) -> bool:
    """Убрать фото с витрины (файл остаётся — на него могут ссылаться старые сообщения)."""
    image = next((i for i in product.images if i.id == image_id and i.is_active), None)
    if image is None:
        return False
    image.is_active = False
    await session.flush()
    return True


async def publish(session: AsyncSession, product: Product, actor_id: int | None) -> None:
    """В продажу: черновик — опубликовать, снятый — вернуть."""
    if not any(ps.is_active for ps in product.product_sizes):
        raise ProductError("Нельзя выставить товар без цен: добавьте хотя бы один размер.")
    product.is_draft = False
    product.is_active = True
    product.updated_by = actor_id
    product.updated_at = utcnow()
    await session.flush()
