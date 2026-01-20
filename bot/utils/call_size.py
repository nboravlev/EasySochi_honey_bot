from sqlalchemy import select, func
from db.models.sizes import Size
from db.db_async import get_async_session
from typing import Dict
from utils.logging_config import structured_logger, LoggingContext

SIZE_MAP: Dict[str, int] = {}  # ключи — нормализованные строки без 'кг', значения — id

async def init_size_map():
    """Заполнить SIZE_MAP всеми размерами из таблицы Size"""
    global SIZE_MAP
    async with get_async_session() as session:
        result = await session.execute(select(Size))
        sizes = result.scalars().all()
        # Ключи — числа как строки, значения — id
        SIZE_MAP = {str(s.name): s.id for s in sizes}
        # Логируем, но показываем пользователю с единицей
        for s in sizes:
            structured_logger.info(
                "Loaded size",
                action="init_size_map",
                context={
                    "size_id": s.id,
                    "display_name": f"{s.name}кг"
                }
            )

async def get_size_id_async(size_display: str) -> int:
    """
    size_display — строка вида '0.5кг'
    Возвращает id размера
    """
    norm = size_display.replace("кг", "").strip()
    if norm in SIZE_MAP:
        return SIZE_MAP[norm]

    async with get_async_session() as session:
        # Преобразуем строку в число для поиска в numeric
        size_value = float(norm.replace(",", "."))
        q = select(Size).where(Size.name == size_value)
        res = await session.execute(q)
        size = res.scalars().first()
        if size:
            SIZE_MAP[norm] = size.id
            structured_logger.info(
                "Cached size",
                action="get_size_id_async",
                context={
                    "size_display": size_display,
                    "size_id": size.id
                }
            )
            return size.id


    # Не нашли
    structured_logger.warning(f"Size '{size_display}' not found in DB")
    raise KeyError(f"Size '{size_display}' not found in Size table (normalized: '{norm}')")
