import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_db_settings
from utils.logging_config import structured_logger

_db_settings = get_db_settings()

engine = create_async_engine(
    _db_settings.database_url,
    # SQL-лог с параметрами содержит персональные данные — только для локальной отладки
    echo=_db_settings.sql_echo,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,  # объекты не станут «откреплёнными» сразу после commit
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


# --- медленные запросы: текст запроса без параметров (в параметрах бывают персональные данные)
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _query_started(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start", []).append(time.perf_counter())


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _query_finished(conn, cursor, statement, parameters, context, executemany):
    elapsed_ms = (time.perf_counter() - conn.info["query_start"].pop()) * 1000
    if elapsed_ms >= _db_settings.slow_query_ms:
        structured_logger.warning(
            f"Slow query: {elapsed_ms:.0f} ms",
            action="db_slow_query",
            execution_time=round(elapsed_ms / 1000, 3),
            context={"statement": " ".join(statement.split())[:500]},
        )
