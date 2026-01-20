from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.db import Base


class DeliveryStatus(Base):
    __tablename__ = "delivery_statuses"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)  # пример: "pending", "in_progress", "delivered"

    # обратная связь с доставками
    deliveries = relationship("OrderDelivery", back_populates="delivery_status")

    def __repr__(self):
        return f"<DeliveryStatus(id={self.id}, name='{self.name}')>"
