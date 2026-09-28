from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship

from db.base import Base
from utils.timeutils import utcnow


class TastingEvent(Base):
    """Мероприятие-дегустация: создаётся рассылкой менеджера."""
    __tablename__ = "tasting_events"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="CASCADE"), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    signups = relationship("TastingSignup", back_populates="event")

    def __repr__(self):
        return f"<TastingEvent(id={self.id}, starts_at={self.starts_at})>"


class TastingSignup(Base):
    """Запись пользователя на дегустацию: waiting → invited → going/declined (domain.enums.TastingStatus)."""
    __tablename__ = "tasting_signups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'invited', 'going', 'declined')", name="check_tasting_signup_status"
        ),
        # в листе ожидания магазина пользователь стоит не больше одного раза
        Index(
            "uq_tasting_signups_waiting_user", "shop_id", "user_id",
            unique=True, postgresql_where=text("status = 'waiting'"),
        ),
        Index("ix_tasting_signups_event_status", "event_id", "status"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(Integer, ForeignKey("public.tasting_events.id", ondelete="CASCADE"), nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'waiting'"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    event = relationship("TastingEvent", back_populates="signups")

    def __repr__(self):
        return f"<TastingSignup(id={self.id}, user={self.user_id}, status={self.status})>"
