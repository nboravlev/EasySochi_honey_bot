# schemas/apartment_type.py
from pydantic import BaseModel

class ProductTypeOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True
