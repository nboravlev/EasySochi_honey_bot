from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from db.base import Base


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"
    __table_args__ = (
        UniqueConstraint("shop_id", "name", name="uq_delivery_zones_shop_name"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    cost = Column(Numeric(6, 2), nullable=False)


    delivery = relationship("OrderDelivery", back_populates="delivery_zone")

    def __repr__(self):
        return f"<DeliveryZone(id={self.id}, name='{self.name}', cost={self.cost})>"
