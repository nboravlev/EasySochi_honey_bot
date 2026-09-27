from sqlalchemy import Column, Integer, String, text, DateTime, Boolean, BIGINT, ForeignKey
from sqlalchemy.orm import relationship, validates
from db.base import Base
from utils.timeutils import utcnow
import re

class User(Base):
    __tablename__ = "users"
    __table_args__ =  {"schema": "public"}
    

    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=True, unique=False)
    firstname = Column(String(50), nullable=True, unique=False)
    phone_number = Column(String(20), nullable=True, unique=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # New columns
    tg_user_id = Column(BIGINT, nullable=False, unique=True)  # Telegram user ID
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    is_bot = Column(Boolean, nullable=False, server_default=text("false"))
    source_id = Column(Integer,ForeignKey("public.sources.id", ondelete="SET NULL"),
    nullable=True)
    # Роль для доступа: 1 — пользователь, 4 — менеджер (domain.enums.Role). Владелец — OWNER_ID в .env.
    role_id = Column(Integer, ForeignKey("public.roles.id", ondelete="RESTRICT"),
                     nullable=False, server_default=text("1"))

    # Bidirectional relationship
    sessions = relationship("Session",back_populates="user")
    orders = relationship(
        "Order",
        back_populates="user",
        foreign_keys="Order.tg_user_id",  # строка, потому что Order ещё не определён
    )
    managed_orders = relationship(
        "Order",
        back_populates="manager",
        foreign_keys="Order.manager_id",
    )
    source = relationship("Source", back_populates="users")

    products = relationship("Product", back_populates = "user", lazy = "selectin")

    @validates('phone_number')
    def validate_phone_number(self, key, phone_number):
        if phone_number:
            # Remove all non-digit characters for validation
            digits_only = re.sub(r'\D', '', phone_number)
            if len(digits_only) < 10:
                raise ValueError("Номер телефона не короче 10 цифр")
        return phone_number


    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}',tg_user_id={self.tg_user_id})>"
