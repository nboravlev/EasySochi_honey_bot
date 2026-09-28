from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from db.base import Base
from utils.timeutils import utcnow


class UserIdentity(Base):
    """Учётная запись человека в конкретной платформе (Telegram, VK, …).

    Внутри системы человек — это users.id; платформенные ID живут только здесь.
    Один users.id может иметь несколько identities (объединение аккаунтов).
    """
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_user_identities_provider_external"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)       # domain.enums.Provider
    external_id = Column(String(64), nullable=False)    # ID в платформе (строкой: у VK/MAX свои форматы)
    username = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="identities")

    def __repr__(self):
        return f"<UserIdentity(user={self.user_id}, {self.provider}:{self.external_id})>"
