"""Мультитенантность: магазин (тенант), его точки и служебные каналы."""
from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import relationship

from db.base import Base
from utils.timeutils import utcnow


class Shop(Base):
    """Магазин — тенант: у него свои товары, заказы, менеджеры, точки, зоны доставки и дегустации."""
    __tablename__ = "shops"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), nullable=False, unique=True)   # в ссылках витрины и в настройках
    name = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)        # показывается покупателю
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    locations = relationship("ShopLocation", back_populates="shop", order_by="ShopLocation.id")
    channels = relationship("ShopChannel", back_populates="shop")

    def __repr__(self):
        return f"<Shop(id={self.id}, slug={self.slug!r})>"


class ShopLocation(Base):
    """Точка магазина: склад, пункт самовывоза. Координаты — для карты и расчёта доставки."""
    __tablename__ = "shop_locations"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    is_pickup = Column(Boolean, nullable=False, server_default=text("true"))   # можно забрать заказ
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    opening_hours = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    shop = relationship("Shop", back_populates="locations")

    def __repr__(self):
        return f"<ShopLocation(id={self.id}, shop={self.shop_id}, address={self.address!r})>"


class ShopChannel(Base):
    """Куда слать служебные уведомления магазина в каждой платформе (например, Telegram-группа продавцов)."""
    __tablename__ = "shop_channels"
    __table_args__ = (
        UniqueConstraint("shop_id", "provider", "purpose", name="uq_shop_channels_shop_provider_purpose"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(20), nullable=False)              # domain.enums.Provider
    address = Column(String(64), nullable=False)               # ID чата/беседы в платформе
    purpose = Column(String(20), nullable=False, server_default=text("'staff'"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    shop = relationship("Shop", back_populates="channels")
