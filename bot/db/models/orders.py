from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    String,
    Numeric,
    CheckConstraint,
    DateTime, Boolean, text,
)
from sqlalchemy.orm import relationship
from db.base import Base
from utils.timeutils import utcnow


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("product_count > 0", name="check_product_count_positive"),
        CheckConstraint("total_price >= 0", name="check_total_price_non_negative"),
        {"schema": "public"}
    )

    id = Column(Integer, primary_key=True)
    
    customer_id = Column(Integer, ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="RESTRICT"), nullable=False, index=True)
    # точка выдачи (самовывоз) или отгрузки (доставка)
    location_id = Column(Integer, ForeignKey("public.shop_locations.id", ondelete="SET NULL"), nullable=True)
    product_size_id = Column(Integer, ForeignKey("public.product_sizes.id", ondelete="RESTRICT"), nullable=False)
    status_id = Column(Integer, ForeignKey("public.order_statuses.id", ondelete="RESTRICT"), nullable=False)    
    product_count = Column(Integer, nullable=False)    
    # total_price может быть вычислена на уровне приложения, но сохраняется в БД
    total_price = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    customer_comment = Column(String(255), nullable=True)
    manager_comment = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    session_id = Column(Integer, ForeignKey("public.sessions.id", ondelete="RESTRICT"),nullable=False)
    required_delivery = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Optional: связи
    user = relationship(
        "User",
        back_populates="orders",
        foreign_keys=[customer_id],
    )
    manager = relationship(
        "User",
        back_populates="managed_orders",
        foreign_keys=[manager_id],
    )
    product_size = relationship("ProductSize", back_populates="orders")
    status = relationship("OrderStatus", back_populates="orders")
    order_packages = relationship("OrderPackage", back_populates="order")
    session = relationship("Session",back_populates="orders")
    shop = relationship("Shop")
    location = relationship("ShopLocation")
    delivery = relationship("OrderDelivery", back_populates="order")


    def __repr__(self):
        return f"<Order(id={self.id}, product_size_id={self.product_size_id}, customer={self.customer_id}, shop={self.shop_id}, status={self.status_id})>"

