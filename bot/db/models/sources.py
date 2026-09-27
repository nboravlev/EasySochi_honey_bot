from sqlalchemy import Column, Integer, String, text, DateTime, Boolean, BIGINT
from sqlalchemy.orm import relationship
from db.base import Base
from utils.timeutils import utcnow

class Source(Base):
    __tablename__ = "sources"
    __table_args__ =  {"schema": "public"}
    

    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BIGINT, nullable=True, unique=True)
    suffix = Column(String(50), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Bidirectional relationship
    users = relationship("User", back_populates = "source")

    def __repr__(self):
        return f"<Refferal(id={self.id}, tg_user_id={self.tg_user_id},suffix='{self.suffix}')>"