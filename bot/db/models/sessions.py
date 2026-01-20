from sqlalchemy import Column, Integer, BIGINT, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from db.db import Base

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BIGINT, 
                    ForeignKey("public.users.tg_user_id", ondelete="CASCADE"),
                    nullable = False, unique = False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    finished_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    last_action = Column(JSONB, nullable=True)  # последнее действие пользователя (опционально)

    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    sent_message = Column(Boolean, nullable=False, server_default=text("false"))
    role_id = Column(
        Integer, 
        ForeignKey("public.roles.id", ondelete="SET DEFAULT"), 
        server_default=text("1"),
        nullable=False
    )
    # Bidirectional relationship
        # обратная связь
    user = relationship("User", back_populates="sessions")
    role = relationship("Role", back_populates="sessions")
    orders = relationship("Order", back_populates="session")
    
    def __repr__(self):
        return f"<Session(id={self.id}, user={self.tg_user_id}, Location = {self.location}, role = {self.role_id})>"
