"""/admin — ссылка входа в админку для браузера (менеджеры и владелец).

Ссылка одноразовая и живёт 10 минут; токен — во фрагменте адреса (#login=…): фрагмент не уходит
на сервер и не попадает в логи nginx. Внутри Telegram админка открывается кнопкой в меню менеджера
как Mini App — там ссылка не нужна.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes

from config import get_settings
from db.db_async import get_async_session
from services import admin_auth
from utils.access import get_actor, manager_only
from utils.logging_config import structured_logger

LINK_MINUTES = int(admin_auth.LOGIN_LINK_TTL.total_seconds() // 60)


def admin_url() -> str | None:
    """Адрес админки или None, если витрина (WEBAPP_URL) не подключена."""
    base = get_settings().webapp_url
    return f"{base.rstrip('/')}/admin/" if base else None


@manager_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = admin_url()
    if url is None:
        await update.message.reply_text("Админка не подключена: не задан адрес витрины (WEBAPP_URL).")
        return
    if update.effective_chat.type != "private":
        # ссылка даёт вход в админку — в группе её увидят все участники
        await update.message.reply_text("Команда /admin работает только в личном чате с ботом.")
        return

    actor = await get_actor(update)
    async with get_async_session() as session:
        token = await admin_auth.issue_login_token(session, actor.user_id)
        await session.commit()
    structured_logger.info("Admin login link issued", user_id=actor.user_id, action="admin_link_issued")
    await update.message.reply_text(
        f"🔐 Вход в админку в браузере. Ссылка одноразовая, действует {LINK_MINUTES} минут — "
        "никому её не пересылайте.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Открыть админку", url=f"{url}#login={token}")]]),
    )


admin_handlers = [CommandHandler("admin", admin_command)]
