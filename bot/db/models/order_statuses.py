from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.db import Base

class OrderStatus(Base):
    __tablename__ = "order_statuses"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    
    # Bidirectional relationship
    orders = relationship("Order", back_populates="status")
