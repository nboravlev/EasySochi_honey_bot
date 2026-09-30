"""Команды владельца платформы: менеджеры магазинов.

/managers                          — список менеджеров (с магазином) и кнопки «снять»
/manager_add @username [магазин]   — назначить менеджером магазина (slug; по умолчанию — магазин-витрина).
                                     Вместо @username можно Telegram ID. Человек должен хотя бы раз нажать /start.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from db.db_async import get_async_session
from db.models import User
from domain.enums import Provider
from domain.messages import OutMessage, ToUser
from services import shops
from services.users import find_user, list_managers, set_manager
from utils.access import is_owner, owner_only
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.delivery import notify

USAGE = (
    "Назначить: <code>/manager_add @username</code> или <code>/manager_add 123456789</code> (Telegram ID).\n"
    "В другой магазин: <code>/manager_add @username slug-магазина</code>."
)


def _telegram_id(user: User) -> str | None:
    return next((i.external_id for i in user.identities if i.provider == Provider.TELEGRAM), None)


def _label(user: User) -> str:
    name = user.firstname or "без имени"
    username = user.username or next((i.username for i in user.identities if i.username), None)
    who = f"{name} (@{username})" if username else f"{name} [{_telegram_id(user) or user.id}]"
    return f"{who} — {user.shop.name}" if user.shop else who


async def _render(session) -> tuple[str, InlineKeyboardMarkup | None]:
    managers = await list_managers(session)
    if not managers:
        return f"Менеджеров пока нет.\n\n{USAGE}", None
    lines = ["👥 <b>Менеджеры</b>\n"] + [f"• {safe_html(_label(u))}" for u in managers] + [f"\n{USAGE}"]
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"❌ Снять: {_label(u)}"[:60], callback_data=f"mgr_remove_{u.id}")] for u in managers]
    )
    return "\n".join(lines), keyboard


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
        if len(context.args) > 1:
            shop = await shops.get_by_slug(session, context.args[1])
        else:
            storefront_id = await shops.storefront_shop_id(session)
            shop = await shops.get_shop(session, storefront_id) if storefront_id else None
        if shop is None:
            await update.message.reply_text("Магазин не найден. Укажите slug магазина вторым словом.")
            return

        user = await find_user(session, ref)
        if user is None:
            await update.message.reply_text(
                f"Пользователь {safe_html(ref)} не найден. Попросите его сначала нажать /start в боте.",
                parse_mode="HTML",
            )
            return
        await set_manager(session, user, shop.id)
        await session.commit()
        user_id, shop_name = user.id, shop.name
        text, keyboard = await _render(session)

    structured_logger.info("Manager added", action="manager_added", context={"user_id": user_id, "shop": shop_name})
    await notify(
        context.bot, ToUser(user_id),
        OutMessage(f"🐝 Вам выданы права менеджера магазина «{safe_html(shop_name)}». Нажмите /start, чтобы открыть меню."),
        "manager_added",
    )
    await update.message.reply_text(
        f"✅ Теперь менеджер магазина «{safe_html(shop_name)}».\n\n{text}", reply_markup=keyboard, parse_mode="HTML"
    )


@owner_only
async def manager_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = int(query.data.rsplit("_", 1)[-1])
    async with get_async_session() as session:
        user = await session.get(User, user_id)
        telegram_id = None
        if user is not None:
            await session.refresh(user, ["identities"])
            telegram_id = _telegram_id(user)
        if telegram_id is not None and is_owner(int(telegram_id)):
            await query.answer("Владельца снять нельзя — он задаётся OWNER_ID в .env.", show_alert=True)
            return
        if user is not None:
            await set_manager(session, user, None)
            await session.commit()
        text, keyboard = await _render(session)

    await query.answer("Права менеджера сняты." if user else "Пользователь не найден.")
    if user is not None:
        structured_logger.info("Manager removed", action="manager_removed", context={"user_id": user_id})
        await notify(context.bot, ToUser(user_id), OutMessage("Права менеджера медового бота сняты."), "manager_removed")
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


managers_handlers = [
    CommandHandler("managers", managers_command),
    CommandHandler("manager_add", manager_add_command),
    CallbackQueryHandler(manager_remove_callback, pattern=r"^mgr_remove_\d+$"),
]
