"""Форматы запросов и ответов API. Деньги — строкой с копейками («1500.00»), время — ISO 8601 в UTC."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from utils.constants import MAX_COMMENT_LENGTH, MAX_PRODUCT_COUNT


class LocationOut(BaseModel):
    id: int
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    opening_hours: str | None = None


class ShopOut(BaseModel):
    id: int
    slug: str
    name: str
    phone: str | None = None
    locations: list[LocationOut] = []


class ShopRef(BaseModel):
    id: int
    name: str


class TypeOut(BaseModel):
    id: int
    name: str


class OfferOut(BaseModel):
    id: int                 # product_size_id — его передают при заказе
    size: str               # «0.5» (кг)
    price: Decimal


class ProductOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    type: TypeOut
    shop: ShopRef
    photos: list[str] = []  # URL фото, первое — обложка
    offers: list[OfferOut]


class CatalogOut(BaseModel):
    shop: ShopOut | None     # витрина одного магазина; None — маркетплейс
    types: list[TypeOut]     # сорта, в которых есть товары
    products: list[ProductOut]


class ConfigOut(BaseModel):
    bot_url: str | None      # ссылка на бота: оформить заказ вне Telegram
    marketplace: bool


class MeOut(BaseModel):
    id: int
    first_name: str | None = None
    phone: str | None = None


class MeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    # телефон для связи продавца; пустая строка — удалить
    phone: str | None = Field(default=None, max_length=20, pattern=r"^$|^\+?[\d\s()-]{5,20}$")


class OrderCreate(BaseModel):
    product_size_id: int
    quantity: int = Field(default=1, ge=1, le=MAX_PRODUCT_COUNT)
    comment: str = Field(default="", max_length=MAX_COMMENT_LENGTH)


class OrderStatusOut(BaseModel):
    code: str                # created, processing, ready, customer_notified, received, declined
    title: str


class OrderOut(BaseModel):
    id: int
    status: OrderStatusOut
    product_name: str
    size: str
    quantity: int
    total: Decimal
    comment: str | None = None
    decline_reason: str | None = None
    created_at: datetime
    pickup: LocationOut | None = None
    shop: ShopRef
