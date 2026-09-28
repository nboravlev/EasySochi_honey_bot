from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base
from utils.timeutils import utcnow


class Notification(Base):
    """Очередь исходящих уведомлений (outbox): одна строка — одно сообщение в одну платформу.

    Строка пишется в той же транзакции, что и событие (заказ подтверждён и т.п.), поэтому
    уведомление не теряется, если Telegram недоступен или процесс перезапустился.
    Отправляет адаптер платформы (utils.telegram_delivery для Telegram), повторяя с паузами.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="check_notification_status"),
        Index("ix_notifications_due", "provider", "next_attempt_at", postgresql_where=text("status = 'pending'")),
        Index("ix_notifications_created_at", "created_at"),
        {"schema": "public"},
    )

    id = Column(BigInteger, primary_key=True)
    kind = Column(String(40), nullable=False)               # событие: order_confirmed, tasting_invite, …
    provider = Column(String(20), nullable=False)           # domain.enums.Provider
    address = Column(String(64), nullable=False)            # чат в платформе
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True, index=True)
    shop_id = Column(Integer, ForeignKey("public.shops.id", ondelete="SET NULL"), nullable=True)
    payload = Column(JSONB, nullable=False)                 # domain.messages.OutMessage.to_payload()
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()"))
    last_error = Column(Text, nullable=True)
    external_message_id = Column(String(64), nullable=True)  # ID отправленного сообщения в платформе
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()"))
    sent_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Notification(id={self.id}, {self.kind} → {self.provider}:{self.address}, {self.status})>"
