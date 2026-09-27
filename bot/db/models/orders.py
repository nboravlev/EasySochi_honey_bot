from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    String,
    Numeric,
    CheckConstraint,
    DateTime,Boolean, text, BIGINT
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
    
    tg_user_id = Column(BIGINT, 
                    ForeignKey("public.users.tg_user_id", ondelete="RESTRICT"),
                    nullable = False, unique = False)
    manager_id = Column(
        BIGINT,
        ForeignKey("public.users.tg_user_id", ondelete="SET NULL"),
        nullable=True, unique = False)
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
        foreign_keys=[tg_user_id],   # <── указываем, какой FK использовать
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
    delivery = relationship("OrderDelivery", back_populates="order")


    def __repr__(self):
        return f"<Order(id={self.id}, product_size_id={self.product_size_id}, user={self.tg_user_id}, status={self.status_id})>"

