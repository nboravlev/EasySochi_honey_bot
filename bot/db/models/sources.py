from sqlalchemy import Column, Integer, String, ForeignKey, text, DateTime, Boolean, BIGINT, UniqueConstraint
from sqlalchemy.orm import relationship, validates
from datetime import datetime
from db.db import Base
import re

class Source(Base):
    __tablename__ = "sources"
    __table_args__ =  {"schema": "public"}
    

    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BIGINT, nullable=True, unique=True)
    suffix = Column(String(50), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Bidirectional relationship
    users = relationship("User", back_populates = "source")

    def __repr__(self):
        return f"<Refferal(id={self.id}, tg_user_id={self.tg_user_id},suffix='{self.suffix}')>"