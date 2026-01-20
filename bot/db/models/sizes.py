from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from db.db import Base
import re

class Size(Base):
    __tablename__ = "sizes"
    __table_args__ =  {"schema": "public"}


    id = Column(Integer, primary_key=True)
    name = Column(Numeric(2,1), nullable=False, unique=True)
    volume_ml = Column(Integer, nullable=True)
    package_id = Column(Integer, ForeignKey("public.packages.id", ondelete="CASCADE"),nullable=False)

    # Bidirectional relationship
    product_sizes = relationship("ProductSize",back_populates="sizes",lazy="selectin")
    package = relationship("Package", back_populates="size",lazy="selectin")
