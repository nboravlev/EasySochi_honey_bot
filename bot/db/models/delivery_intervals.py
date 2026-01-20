from sqlalchemy import Column, Integer, String, Time
from sqlalchemy.orm import relationship
from db.db import Base

class DeliveryInterval(Base):
    __tablename__ = "delivery_intervals"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    start_interval = Column(Time, nullable=False)
    end_interval = Column(Time, nullable=False)
    
    order_deliverys = relationship("OrderDelivery", back_populates="delivery_interval")

    @property
    def display_interval(self) -> str:
        """Возвращает интервал в удобном виде для сообщений пользователю"""
        start = self.start_interval.strftime("%H:%M")
        end = self.end_interval.strftime("%H:%M")
        return f"с {start} до {end}"
    
    def __repr__(self):
        return (
            f"<DeliveryInterval(id={self.id}, name='{self.name}', "
            f"interval='{self.start_interval} - {self.end_interval}')>"
        )
