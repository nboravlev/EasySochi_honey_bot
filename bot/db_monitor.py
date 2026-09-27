"""Мониторинг: доступность БД (сообщения в чат) и heartbeat-файл для docker healthcheck."""
import time
from pathlib import Path

from sqlalchemy import text

from config import get_settings
from db.db_async import get_async_session
from utils.logging_config import structured_logger

DB_CHECK_INTERVAL_SEC = 60
HEARTBEAT_INTERVAL_SEC = 30


class _DbState:
    ok: bool | None = None          # None — ещё не проверяли
    last_report: float = float("-inf")


_state = _DbState()


async def _db_is_available() -> bool:
    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        structured_logger.error("Database health check failed", action="db_health_check_failed", exception=e)
        return False


def _message(ok: bool, changed: bool) -> str:
    if changed:
        return ("✅ <b>База данных honeybot снова доступна</b>" if ok
                else "🚨 <b>База данных honeybot недоступна!</b>")
    return "🐝 <b>База данных honeybot доступна</b>" if ok else "❄️ <b>База данных honeybot недоступна!</b>"


async def check_db(context):
    """Раз в минуту: при смене состояния — сообщение сразу, иначе — heartbeat раз в N минут."""
    settings = get_settings()
    ok = await _db_is_available()
    now = time.monotonic()

    changed = _state.ok is not None and ok != _state.ok
    heartbeat_minutes = settings.db_monitor_heartbeat_minutes
    heartbeat_due = heartbeat_minutes > 0 and now - _state.last_report >= heartbeat_minutes * 60
    first_failure = _state.ok is None and not ok
    _state.ok = ok

    if changed:
        structured_logger.warning(
            "Database availability changed", action="db_state_changed", context={"available": ok}
        )
    if not (changed or heartbeat_due or first_failure):
        return

    try:
        await context.bot.send_message(
            chat_id=settings.db_monitor_chat_id, text=_message(ok, changed), parse_mode="HTML"
        )
        _state.last_report = now
    except Exception as send_error:
        structured_logger.warning(
            "Failed to send DB status message",
            action="db_health_notify_failed",
            context={"chat_id": settings.db_monitor_chat_id, "error": str(send_error)}
        )


async def write_heartbeat(context) -> None:
    """Файл обновляется, пока жив event loop и JobQueue; зависший бот перестаёт его обновлять."""
    try:
        Path(get_settings().heartbeat_file).write_text(str(int(time.time())))
    except OSError as e:
        structured_logger.warning("Heartbeat write failed", action="heartbeat_failed", context={"error": str(e)})
