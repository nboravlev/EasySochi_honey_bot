from sqlalchemy import Column, Integer, String, Numeric
from sqlalchemy.orm import relationship
from db.db import Base

class Package(Base):
    __tablename__ = "packages"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    price = Column(Numeric(4,1), nullable=False)

    # Bidirectional relationship
    # Связи
    size = relationship(
        "Size",
        back_populates="package",
        cascade="all, delete-orphan"
    )
    order_package = relationship(
        "OrderPackage",
        back_populates="package"
    )