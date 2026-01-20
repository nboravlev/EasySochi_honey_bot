from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    Index,
    text,
)
from sqlalchemy.orm import relationship, backref
from geoalchemy2 import Geometry
from datetime import datetime
from db.db import Base


class OrderDelivery(Base):
    __tablename__ = "order_delivery"
    __table_args__ = (
        Index("idx_order_delivery_point_gix", "delivery_point", postgresql_using="gist"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)

    order_id = Column(
        Integer,
        ForeignKey("public.orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    delivery_address = Column(String(255), nullable=False)
    delivery_address_short = Column(String(100), nullable=True)

    delivery_point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    if_within = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    delivery_zone_id = Column(
        Integer,
        ForeignKey("public.delivery_zones.id", ondelete="SET NULL"),
        nullable=True,
    )

    delivery_date = Column(DateTime, nullable=False)

    delivery_interval_id = Column(
        Integer,
        ForeignKey("public.delivery_intervals.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # новая колонка — зафиксированная стоимость доставки (в рублях на момент оформления заказа)
    delivery_cost = Column(Numeric(6, 2), nullable=False, default=0)

    # статус доставки
    delivery_status_id = Column(
        Integer,
        ForeignKey("public.delivery_statuses.id", ondelete="RESTRICT"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # связи
    order = relationship("Order", back_populates="delivery", lazy="joined")
    delivery_zone = relationship("DeliveryZone", back_populates="delivery", lazy="joined")
    delivery_interval = relationship("DeliveryInterval", back_populates="order_deliverys", lazy="joined")
    delivery_status = relationship("DeliveryStatus", back_populates="deliveries", lazy="joined")

    def __repr__(self):
        return (
            f"<OrderDelivery(id={self.id}, order_id={self.order_id}, "
            f"zone_id={self.delivery_zone_id}, status_id={self.delivery_status_id}, "
            f"cost={self.delivery_cost}, if_within={self.if_within})>"
        )
