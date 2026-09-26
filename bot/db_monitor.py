from sqlalchemy import text

from config import get_settings
from db.db_async import get_async_session
from utils.logging_config import structured_logger


async def check_db(context):
    """Каждые 30 минут шлёт в мониторинговый чат статус БД (намеренно всегда, как heartbeat)."""
    bot = context.bot
    chat_id = get_settings().db_monitor_chat_id

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

    text_msg = (
        "🐝 <b>База данных honeybot доступна</b>"
        if status_ok
        else "❄️ <b>База данных honeybot недоступна!</b>"
    )

    try:
        await bot.send_message(chat_id=chat_id, text=text_msg, parse_mode="HTML")
    except Exception as send_error:
        structured_logger.warning(
            "Failed to send DB status message",
            action="db_health_notify_failed",
            context={"chat_id": chat_id, "error": str(send_error)}
        )
