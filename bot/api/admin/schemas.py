"""Форматы API админки. Деньги — строкой с копейками, время — ISO 8601 в UTC."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas import LocationOut, OrderStatusOut, ShopRef
from services.order_actions import StaffAction
from utils.constants import MAX_PRODUCT_NAME_LENGTH

# --- вход


class LoginIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class AdminMe(BaseModel):
    user_id: int
    name: str | None
    is_owner: bool
    shop: ShopRef | None           # магазин менеджера
    via: Literal["telegram", "session"]


# --- заказы


class CustomerOut(BaseModel):
    id: int
    name: str | None
    phone: str | None
    telegram_username: str | None = None
    vk_url: str | None = None


class AdminOrderOut(BaseModel):
    id: int
    status: OrderStatusOut
    shop: ShopRef
    product_name: str
    size: str
    quantity: int
    total: Decimal
    comment: str | None
    decline_reason: str | None
    created_at: datetime
    updated_at: datetime | None
    customer: CustomerOut
    manager: str | None            # кто подтвердил
    pickup: LocationOut | None
    actions: list[StaffAction]     # что можно сделать сейчас


class OrderPage(BaseModel):
    items: list[AdminOrderOut]
    total: int


class OrderActionIn(BaseModel):
    action: StaffAction
    reason: str = Field(default="", max_length=255)


class DeliveryOut(BaseModel):
    sent: int
    queued: int
    failed: int


class OrderActionOut(BaseModel):
    order: AdminOrderOut
    customer_notified: DeliveryOut


# --- товары


class SizeOut(BaseModel):
    id: int
    kg: str
    package: str | None


class TypeOut(BaseModel):
    id: int
    name: str


class ReferenceOut(BaseModel):
    sizes: list[SizeOut]
    types: list[TypeOut]


class TypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class AdminOfferOut(BaseModel):
    id: int
    size_id: int
    kg: str
    price: Decimal
    active: bool


class PhotoOut(BaseModel):
    id: int
    url: str | None


class AdminProductOut(BaseModel):
    id: int
    name: str
    description: str | None
    type: TypeOut
    shop: ShopRef
    state: Literal["draft", "published", "withdrawn"]
    offers: list[AdminOfferOut]
    photos: list[PhotoOut]
    updated_at: datetime | None


class OfferIn(BaseModel):
    size_id: int
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    active: bool = True


class ProductCreate(BaseModel):
    shop_id: int | None = None     # владельцу — обязательно; менеджеру — его магазин
    name: str = Field(min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    type_id: int
    description: str = Field(default="", max_length=2000)
    offers: list[OfferIn] = Field(min_length=1)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    type_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)


# --- магазины и менеджеры


class AdminLocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    opening_hours: str | None = Field(default=None, max_length=255)
    is_pickup: bool = True
    is_active: bool = True


class AdminLocationOut(LocationOut):
    is_pickup: bool
    is_active: bool


class AdminShopOut(BaseModel):
    id: int
    slug: str
    name: str
    phone: str | None
    is_active: bool
    is_storefront: bool
    staff_chat_id: str | None      # служебный Telegram-чат
    locations: list[AdminLocationOut]
    managers: int


class ShopCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class StaffChatIn(BaseModel):
    # ID Telegram-группы продавцов (отрицательное число); пусто — убрать
    telegram_chat_id: int | None


class ManagerOut(BaseModel):
    user_id: int
    name: str | None
    telegram_id: str | None
    username: str | None
    shop: ShopRef | None
    is_owner: bool


class ManagerIn(BaseModel):
    user: str = Field(min_length=2, max_length=64)    # @username или Telegram ID
    shop_id: int


# --- статистика и очередь


class BucketOut(BaseModel):
    count: int
    total: Decimal


class ProductSalesOut(BaseModel):
    name: str
    kg: Decimal
    total: Decimal


class TastingOut(BaseModel):
    starts_at: datetime
    invited: int
    going: int
    declined: int


class StatsOut(BaseModel):
    period_days: int | None
    sales: list[ProductSalesOut]
    new: BucketOut
    in_progress: BucketOut
    completed: BucketOut
    declined: BucketOut
    customers: int
    tasting_waiting: int
    next_tasting: TastingOut | None


class NotificationOut(BaseModel):
    id: int
    kind: str
    provider: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    next_attempt_at: datetime
    user_id: int | None
    shop_id: int | None
    text: str
