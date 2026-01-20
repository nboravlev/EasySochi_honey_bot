from sqlalchemy import Column, Integer, String, Numeric
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from db.db import Base


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    cost = Column(Numeric(6, 2), nullable=False)


    delivery = relationship("OrderDelivery", back_populates="delivery_zone")

    def __repr__(self):
        return f"<DeliveryZone(id={self.id}, name='{self.name}', cost={self.cost})>"
