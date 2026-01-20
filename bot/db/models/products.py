from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    CheckConstraint,
    text,
    BIGINT
)
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from datetime import datetime
from db.db import Base

from decimal import Decimal


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="check_quantity_nonnegative"),
        {"schema": "public"}
        )
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    type_id = Column(Integer, ForeignKey("public.product_types.id", ondelete="RESTRICT"), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(BIGINT, 
                    ForeignKey("public.users.tg_user_id", ondelete="CASCADE"),
                    nullable = False, unique = False)
    updated_by = Column(BIGINT,nullable = True, unique = False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_draft = Column(Boolean, nullable=False, default=True, server_default=text("true"))  
    quantity = Column(Numeric(5,1),nullable=True)

    # отношения (опционально)
# Связи
    product_type = relationship(
        "ProductType",
        back_populates="products",
        lazy="joined"  # всегда загружаем вместе, т.к. это FK
    )
    product_sizes = relationship(
        "ProductSize",
        back_populates="product",
        lazy="selectin",  # оптимально для коллекций
        cascade="all, delete-orphan"
    )
    images = relationship(
        "Image",
        back_populates="product",
        lazy="selectin"
    )
    user = relationship("User",
                        back_populates="products",
                        lazy="selectin")


    def __repr__(self):
        return f"<Product(id={self.id}, name={self.name}, quantity={self.quantity})>"
