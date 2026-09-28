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
)
from sqlalchemy.orm import relationship
from db.base import Base
from utils.timeutils import utcnow



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
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # товар принадлежит магазину; автор карточки — для истории
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
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
    shop = relationship("Shop")
    author = relationship("User", foreign_keys=[created_by])


    def __repr__(self):
        return f"<Product(id={self.id}, name={self.name}, quantity={self.quantity})>"
