from sqlalchemy import Column, Integer, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from db.db import Base

class OrderPackage(Base):
    __tablename__ = "order_packages"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("public.orders.id", ondelete="RESTRICT"),nullable=False)
    package_id = Column(Integer, ForeignKey("public.packages.id", ondelete="RESTRICT"),nullable=False)

    # bidirectional relationship
    order = relationship("Order", back_populates="order_packages")
    package = relationship("Package", back_populates="order_package")
