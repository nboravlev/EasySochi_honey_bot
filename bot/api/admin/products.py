"""Товары в админке: карточки во всех состояниях, правка, цены по размерам, фото, продажа."""
import asyncio

from fastapi import APIRouter, HTTPException, UploadFile, status

from api.admin.deps import CurrentStaff, OwnerStaff, Staff
from api.admin.schemas import (
    AdminOfferOut,
    AdminProductOut,
    OfferIn,
    PhotoOut,
    ProductCreate,
    ProductUpdate,
    ReferenceOut,
    SizeOut,
    TypeIn,
    TypeOut,
)
from api.deps import DbSession
from api.routes.public import media_url
from api.schemas import ShopRef
from db.models import Product
from services import catalog, media, product_admin, shops
from services.product_admin import ProductError
from utils.logging_config import structured_logger

router = APIRouter(tags=["админка: товары"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def product_out(product: Product) -> AdminProductOut:
    return AdminProductOut(
        id=product.id, name=product.name, description=product.description,
        type=TypeOut(id=product.product_type.id, name=product.product_type.name),
        shop=ShopRef(id=product.shop.id, name=product.shop.name),
        state=product_admin.state(product),
        offers=sorted(
            (AdminOfferOut(id=ps.id, size_id=ps.size_id, kg=f"{ps.sizes.name}", price=ps.price, active=ps.is_active)
             for ps in product.product_sizes),
            key=lambda o: (not o.active, float(o.kg)),
        ),
        photos=[PhotoOut(id=i.id, url=media_url(i.storage_key))
                for i in sorted(product.images, key=lambda i: i.id) if i.is_active],
        updated_at=product.updated_at,
    )


def _bad(exc: ProductError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


async def _load(session, staff: Staff, product_id: int) -> Product:
    product = await product_admin.get(session, product_id, staff.scope)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Товар не найден.")
    return product


@router.get("/reference", response_model=ReferenceOut)
async def reference(staff: CurrentStaff, session: DbSession) -> ReferenceOut:
    """Справочники для формы товара: размеры банок и сорта."""
    return ReferenceOut(
        sizes=[SizeOut(id=s.id, kg=f"{s.name}", package=s.package.name if s.package else None)
               for s in await product_admin.sizes(session)],
        types=[TypeOut(id=t.id, name=t.name) for t in await product_admin.types(session)],
    )


@router.post("/types", response_model=TypeOut, status_code=status.HTTP_201_CREATED)
async def create_type(body: TypeIn, staff: OwnerStaff, session: DbSession) -> TypeOut:
    """Новый сорт — общий для всех магазинов, поэтому только владелец."""
    try:
        product_type = await product_admin.create_type(session, body.name)
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return TypeOut(id=product_type.id, name=product_type.name)


@router.get("/products", response_model=list[AdminProductOut])
async def list_products(staff: CurrentStaff, session: DbSession, shop_id: int | None = None) -> list[AdminProductOut]:
    return [product_out(p) for p in await product_admin.list_products(session, staff.shop_filter(shop_id))]


@router.get("/products/{product_id}", response_model=AdminProductOut)
async def get_product(product_id: int, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    return product_out(await _load(session, staff, product_id))


@router.post("/products", response_model=AdminProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductCreate, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    """Новая карточка — черновик: покупатели её не видят, пока не нажать «В продажу»."""
    shop_id = body.shop_id if staff.is_owner else staff.shop_id
    if shop_id is None or await shops.get_shop(session, shop_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Выберите магазин.")
    try:
        product = await product_admin.create(
            session, shop_id=shop_id, author_id=staff.user.id, name=body.name, type_id=body.type_id,
            description=body.description, offers=[(o.size_id, o.price) for o in body.offers if o.active],
        )
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    structured_logger.info("Product draft created in admin", user_id=staff.user.id, action="admin_product_created",
                           context={"product_id": product.id, "shop_id": shop_id})
    return product_out(product)


@router.patch("/products/{product_id}", response_model=AdminProductOut)
async def update_product(product_id: int, body: ProductUpdate, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    product = await _load(session, staff, product_id)
    try:
        await product_admin.update(session, product, staff.user.id, name=body.name, type_id=body.type_id,
                                   description=body.description)
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return product_out(await _load(session, staff, product_id))


@router.put("/products/{product_id}/offers", response_model=AdminProductOut)
async def set_offers(product_id: int, body: list[OfferIn], staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    """Цены по размерам целиком: неперечисленные размеры снимаются с продажи."""
    product = await _load(session, staff, product_id)
    try:
        await product_admin.set_offers(session, product, [(o.size_id, o.price, o.active) for o in body], staff.user.id)
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return product_out(await _load(session, staff, product_id))


@router.post("/products/{product_id}/photos", response_model=AdminProductOut)
async def upload_photo(product_id: int, file: UploadFile, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    """Фото товара: квадрат по центру, до 1024 px, в своё хранилище (как фото из бота)."""
    product = await _load(session, staff, product_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Файл больше 15 МБ.")
    try:
        key = await asyncio.to_thread(media.save_product_photo, data)
    except media.InvalidImage as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Это не изображение.") from exc
    try:
        await product_admin.add_photo(session, product, key)
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return product_out(await _load(session, staff, product_id))


@router.delete("/products/{product_id}/photos/{image_id}", response_model=AdminProductOut)
async def remove_photo(product_id: int, image_id: int, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    product = await _load(session, staff, product_id)
    if not await product_admin.remove_photo(session, product, image_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Фото не найдено.")
    await session.commit()
    return product_out(await _load(session, staff, product_id))


@router.post("/products/{product_id}/publish", response_model=AdminProductOut)
async def publish(product_id: int, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    """В продажу: черновик — опубликовать, снятый — вернуть."""
    product = await _load(session, staff, product_id)
    try:
        await product_admin.publish(session, product, staff.user.id)
    except ProductError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return product_out(await _load(session, staff, product_id))


@router.post("/products/{product_id}/withdraw", response_model=AdminProductOut)
async def withdraw(product_id: int, staff: CurrentStaff, session: DbSession) -> AdminProductOut:
    """Снять с продажи (как в боте): нельзя, пока по товару есть незавершённые заказы."""
    await _load(session, staff, product_id)
    result, active = await catalog.withdraw(session, product_id, staff.scope, staff.user.id)
    if result == catalog.WithdrawResult.HAS_ACTIVE_ORDERS:
        numbers = ", ".join(f"№{i}" for i in active)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"Сначала завершите заказы по этому товару: {numbers}.")
    await session.commit()
    return product_out(await _load(session, staff, product_id))
