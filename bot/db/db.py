from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os


# Получаем строку подключения из .env
DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC")
if not DATABASE_URL_SYNC:
    raise ValueError("DATABASE_URL_SYNC is not set in .env")

# Создаём SQLAlchemy Engine
engine = create_engine(DATABASE_URL_SYNC)



# Создаём фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Базовый класс для моделей
Base = declarative_base()

# Утилита для Alembic и скриптов
def get_engine():
    return engine

# Утилита для получения сессии
def get_session():
    return SessionLocal()