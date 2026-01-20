from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    String,
    Date,
    Numeric,
    CheckConstraint,
    DateTime,Boolean, text, Index,
    BIGINT
)
from sqlalchemy.orm import relationship
from db.db import Base
from datetime import datetime


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("drink_count > 0", name="check_drink_count_positive"),
        CheckConstraint("total_price >= 0", name="check_total_price_non_negative"),
        {"schema": "public"}
    )

    id = Column(Integer, primary_key=True)
    
    tg_user_id = Column(BIGINT, 
                    ForeignKey("public.users.tg_user_id", ondelete="CASCADE"),
                    nullable = False, unique = False)
    manager_id = Column(
        BIGINT,
        ForeignKey("public.users.tg_user_id", ondelete="SET NULL"),
        nullable=True, unique = False)
    product_size_id = Column(Integer, ForeignKey("public.product_sizes.id", ondelete="CASCADE"), nullable=False)
    status_id = Column(Integer, ForeignKey("public.order_statuses.id", ondelete="CASCADE"), nullable=False)    
    product_count = Column(Integer, nullable=False)    
    # total_price может быть вычислена на уровне приложения, но сохраняется в БД
    total_price = Column(Numeric(5,1), nullable=False)    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
        return f"<Order(id={self.id}, name={self.drinks.name}, user={self.tg_user_id},status ={self.status_id})>"

