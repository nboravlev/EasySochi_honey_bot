from sqlalchemy import (
    Column,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    text
)
from sqlalchemy.orm import relationship
from datetime import datetime
from db.base import Base



class ProductSize(Base):
    __tablename__ = "product_sizes"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("public.products.id", ondelete="CASCADE"), nullable=False)
    size_id = Column(Integer, ForeignKey("public.sizes.id", ondelete="CASCADE"), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))


    # отношения (опционально)
    product = relationship("Product", back_populates="product_sizes")
    productsize_images = relationship("ProductsizeImage",back_populates="product_size")
    sizes = relationship("Size", back_populates = "product_sizes")
    orders = relationship("Order", back_populates="product_size")

