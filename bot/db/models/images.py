from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Boolean,
    DateTime,
    String,
    text
)
from db.base import Base
from utils.timeutils import utcnow
from sqlalchemy.orm import relationship


class Image(Base):
    __tablename__ = "images"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)

    product_id = Column(Integer, ForeignKey("public.products.id", ondelete="CASCADE"), nullable=False)

    tg_file_id = Column(String, nullable=False)  # идентификатор файла в Telegram
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))  # включено в выдачу

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Optional: связь с Apartment
    product = relationship("Product", back_populates="images")
