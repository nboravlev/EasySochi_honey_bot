from pydantic import BaseModel
from decimal import Decimal

class PackagesOut(BaseModel):
    id: int
    name: str
    price: Decimal

    class Config:
        from_attributes = True
