"""Публичная часть: каталог витрины и настройки для фронтенда. Персональных данных здесь нет."""
from fastapi import APIRouter, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbSession, Notifications
from api.schemas import CatalogOut, ConfigOut, LocationOut, OfferOut, ProductOut, ShopOut, ShopRef, TypeOut
from db.models import Product
from config import get_settings
from services import catalog, shops
from utils import vk_delivery

MEDIA_URL = "/media/"
CATALOG_CACHE_SECONDS = 60


def media_url(storage_key: str | None) -> str | None:
    return f"{MEDIA_URL}{storage_key}" if storage_key else None


def product_out(product: Product) -> ProductOut | None:
    """Товар для витрины; None — если у него не осталось размеров в продаже."""
    offers = sorted(
        (OfferOut(id=s.id, size=f"{s.sizes.name}", price=s.price) for s in product.product_sizes if s.is_active),
        key=lambda o: o.price,
    )
    if not offers:
        return None
    images = sorted((i for i in product.images if i.is_active and i.storage_key), key=lambda i: i.id)
    return ProductOut(
        id=product.id, name=product.name, description=product.description,
        type=TypeOut(id=product.product_type.id, name=product.product_type.name),
        shop=ShopRef(id=product.shop.id, name=product.shop.name),
        photos=[media_url(i.storage_key) for i in images],
        offers=offers,
    )


async def shop_out(session: AsyncSession, shop_id: int) -> ShopOut:
    shop = await shops.get_shop(session, shop_id)
    locations = [
        LocationOut(id=loc.id, name=loc.name, address=loc.address, opening_hours=loc.opening_hours,
                    latitude=point.latitude if point else None, longitude=point.longitude if point else None)
        for loc, point in await shops.active_locations(session, shop_id)
    ]
    return ShopOut(id=shop.id, slug=shop.slug, name=shop.name, phone=shop.contact_phone, locations=locations)


router = APIRouter(tags=["витрина"])


@router.get("/catalog", response_model=CatalogOut)
async def get_catalog(response: Response, session: DbSession) -> CatalogOut:
    """Всё, что сейчас продаётся на витрине (STOREFRONT_SHOP) или во всех магазинах (маркетплейс)."""
    shop_id = await shops.storefront_shop_id(session)
    products = [p for p in map(product_out, await catalog.published_products(session, shop_id)) if p]
    types = {p.type.id: p.type for p in products}
    response.headers["Cache-Control"] = f"public, max-age={CATALOG_CACHE_SECONDS}"
    return CatalogOut(
        shop=await shop_out(session, shop_id) if shop_id is not None else None,
        types=sorted(types.values(), key=lambda t: t.name),
        products=products,
    )


@router.get("/config", response_model=ConfigOut)
async def get_config(session: DbSession, notifier: Notifications) -> ConfigOut:
    settings = get_settings()
    return ConfigOut(
        bot_url=await notifier.bot_url(),
        marketplace=await shops.storefront_shop_id(session) is None,
        vk_group_id=settings.vk_group_id if settings.vk_messages_enabled else None,
        vk_app_url=vk_delivery.app_url() if settings.vk_auth_enabled else None,
    )
