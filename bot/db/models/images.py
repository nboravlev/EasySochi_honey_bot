from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship

from db.base import Base
from utils.timeutils import utcnow


class Image(Base):
    """Фото товара. Файл — в собственном хранилище (services.media, storage_key);
    tg_file_id — кэш Telegram, чтобы не загружать файл при каждой отправке."""
    __tablename__ = "images"
    __table_args__ = (
        CheckConstraint("storage_key IS NOT NULL OR tg_file_id IS NOT NULL", name="check_images_has_source"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True)

    product_id = Column(Integer, ForeignKey("public.products.id", ondelete="CASCADE"), nullable=False)

    storage_key = Column(String(255), nullable=True)   # «products/<uuid>.jpg»; пусто — ещё не скачано из Telegram
    tg_file_id = Column(String, nullable=True)         # идентификатор файла в Telegram (кэш)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))  # включено в выдачу

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    product = relationship("Product", back_populates="images")
