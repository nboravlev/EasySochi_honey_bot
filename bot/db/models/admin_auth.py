from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from db.base import Base
from utils.timeutils import utcnow


class AdminLoginToken(Base):
    """Одноразовая ссылка входа в админку из бота (/admin). Хранится только хеш токена."""
    __tablename__ = "admin_login_tokens"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


class AdminSession(Base):
    """Сессия админки в браузере (cookie). Хранится только хеш; выход и снятие менеджера — revoked_at."""
    __tablename__ = "admin_sessions"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String(255), nullable=True)
