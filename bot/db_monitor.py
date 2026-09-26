import os
from sqlalchemy import text
import asyncio
from db.db_async import get_async_session
from utils.logging_config import structured_logger





# Конфигурация

CHAT_ID = int(os.getenv("DB_MONITOR_CHAT_ID", "-1002843679066"))  # канал или чат

async def check_db(context):
    bot = context.bot

    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        status_ok = True

    except Exception as e:
        status_ok = False
        structured_logger.error(
            "Database health check failed",
            action="db_health_check_failed",
            exception=e
        )


    # ВСЕГДА отправляем статус, без проверки на изменение
    text_msg = (
        "🐝 <b>База данных honeybot доступна</b>"
        if status_ok
        else "❄️ <b>База данных honeybot недоступна!</b>"
    )
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text_msg, parse_mode="HTML")
    except Exception as send_error:
        structured_logger.warning(
            "Failed to send DB status message",
            action="db_health_notify_failed",
            context={"chat_id": CHAT_ID, "error": str(send_error)}
        )

