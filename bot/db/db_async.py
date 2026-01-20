
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import os

from contextlib import asynccontextmanager
from typing import AsyncGenerator

DATABASE_URL = os.getenv("DATABASE_URL")

if not (DATABASE_URL):
    raise RuntimeError("DATABASE_URL are not set in environment variables")

# Двигаем SQLAlchemy в async‑режим
engine = create_async_engine(
    DATABASE_URL,
    echo=True                # включить SQL‑логгинг
)


# factory для сессий
async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # объекты не станут «откреплёнными» сразу после commit
)

#async def get_async_session() -> AsyncSession:
#    """
 #   Контекст‑менеджер для получения AsyncSession.
 #   Используйте в виде:
 #       async with get_async_session() as session:
  #          ...
  #  """
 #   async with async_session_maker() as session:
 #     yield session


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
       yield session

# Базовый класс для моделей
Base = declarative_base()
