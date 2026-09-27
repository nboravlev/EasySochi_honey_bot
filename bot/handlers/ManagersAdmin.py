"""Команды владельца: список менеджеров, назначение и снятие.

/managers                 — список с кнопками «снять»
/manager_add @username    — назначить (или Telegram ID); человек должен хотя бы раз нажать /start
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from db.db_async import get_async_session
from db.models import User
from services.users import find_user, list_managers, set_manager
from utils.access import is_owner, owner_only
from utils.escape import safe_html
from utils.logging_config import structured_logger

USAGE = "Назначить: <code>/manager_add @username</code> или <code>/manager_add 123456789</code> (Telegram ID)."


def _label(user: User) -> str:
    name = user.firstname or "без имени"
    return f"{name} (@{user.username})" if user.username else f"{name} [{user.tg_user_id}]"


async def _render(session) -> tuple[str, InlineKeyboardMarkup | None]:
    managers = await list_managers(session)
    if not managers:
        return f"Менеджеров пока нет.\n\n{USAGE}", None
    lines = ["👥 <b>Менеджеры</b>\n"] + [f"• {safe_html(_label(u))}" for u in managers] + [f"\n{USAGE}"]
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"❌ Снять: {_label(u)}"[:60], callback_data=f"mgr_remove_{u.tg_user_id}")]
         for u in managers]
    )
    return "\n".join(lines), keyboard


async def _tell(context: ContextTypes.DEFAULT_TYPE, tg_user_id: int, text: str) -> None:
    try:
        await context.bot.send_message(chat_id=tg_user_id, text=text)
    except Exception as exc:
        structured_logger.warning(
            "Failed to notify about role change", action="role_notify_failed",
            context={"tg_user_id": tg_user_id, "error": str(exc)},
        )


@owner_only
async def managers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with get_async_session() as session:
        text, keyboard = await _render(session)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


@owner_only
async def manager_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(USAGE, parse_mode="HTML")
        return
    ref = context.args[0]
    async with get_async_session() as session:
        user = await find_user(session, ref)
        if user is None:
            await update.message.reply_text(
                f"Пользователь {safe_html(ref)} не найден. Попросите его сначала нажать /start в боте.",
                parse_mode="HTML",
            )
            return
        await set_manager(session, user, True)
        await session.commit()
        text, keyboard = await _render(session)

    structured_logger.info("Manager added", action="manager_added", context={"tg_user_id": user.tg_user_id})
    await _tell(context, user.tg_user_id, "🐝 Вам выданы права менеджера медового бота. Нажмите /start, чтобы открыть меню.")
    await update.message.reply_text(f"✅ {safe_html(_label(user))} — теперь менеджер.\n\n{text}",
                                    reply_markup=keyboard, parse_mode="HTML")


@owner_only
async def manager_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_user_id = int(query.data.rsplit("_", 1)[-1])
    if is_owner(tg_user_id):
        await query.answer("Владельца снять нельзя — он задаётся OWNER_ID в .env.", show_alert=True)
        return
    async with get_async_session() as session:
        user = await find_user(session, str(tg_user_id))
        if user is not None:
            await set_manager(session, user, False)
            await session.commit()
        text, keyboard = await _render(session)

    await query.answer("Права менеджера сняты." if user else "Пользователь не найден.")
    if user is not None:
        structured_logger.info("Manager removed", action="manager_removed", context={"tg_user_id": tg_user_id})
        await _tell(context, tg_user_id, "Права менеджера медового бота сняты.")
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


managers_handlers = [
    CommandHandler("managers", managers_command),
    CommandHandler("manager_add", manager_add_command),
    CallbackQueryHandler(manager_remove_callback, pattern=r"^mgr_remove_\d+$"),
]
