from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.db import Base

class ProductType(Base):
    __tablename__ = "product_types"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    
    # Bidirectional relationship
    products = relationship("Product", back_populates="product_type")
    
 