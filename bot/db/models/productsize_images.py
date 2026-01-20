from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Boolean,
    DateTime,
    String,
    text
)
from db.db import Base
from sqlalchemy.orm import relationship
from datetime import datetime


class ProductsizeImage(Base):
    __tablename__ = "productsize_images"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)

    product_size_id = Column(Integer, ForeignKey("public.product_sizes.id", ondelete="CASCADE"), nullable=False)

    tg_file_id = Column(String, nullable=False)  # идентификатор файла в Telegram
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))  # включено в выдачу

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Optional: связь с Apartment
    product_size = relationship("ProductSize", back_populates="productsize_images")
