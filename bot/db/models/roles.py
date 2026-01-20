from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.db import Base

class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    
    # Bidirectional relationship
    sessions = relationship("Session", back_populates="role")
    
    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}')>"