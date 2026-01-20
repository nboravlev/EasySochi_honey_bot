# api/routes/static_data.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.db_async import get_async_session
from db.models.product_types import ProductType
from db.models.packages import Package
from schemas.product_types import ProductTypeOut
from schemas.packages import PackagesOut
from typing import List
from sqlalchemy import select

router = APIRouter()

@router.get("/product_types/", response_model=List[ProductTypeOut])
async def get_product_types(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(ProductType))
    return result.scalars().all()

@router.get("/packages/", response_model=List[PackagesOut])
async def get_packages(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Package))
    return result.scalars().all()