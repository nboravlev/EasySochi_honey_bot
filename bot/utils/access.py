"""Кто действует и что ему можно — для Telegram-адаптера.

- Владелец платформы — OWNER_ID (Telegram ID) в .env: управляет всеми магазинами и назначает менеджеров.
- Менеджер — users.role_id = MANAGER и users.shop_id: работает в одном магазине.
- Сотрудник магазина — менеджер этого магазина или участник его служебного чата (shop_channels).

Внутри системы человек — users.id; Telegram ID используется только здесь, на входе.
"""
from dataclasses import dataclass
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import get_settings
from db.db_async import get_async_session
from domain.enums import Provider
from services import identity, shops
from services.users import StaffProfile, get_staff_profile
from utils.logging_config import structured_logger

DENIED_TEXT = "🚫 Недостаточно прав для этого действия."

# Telegram ID → users.id не меняется: кэшируем навсегда (незарегистрированных не кэшируем)
_user_ids: dict[int, int] = {}


def remember_user(telegram_id: int, user_id: int) -> None:
    _user_ids[telegram_id] = user_id


def forget_users() -> None:
    _user_ids.clear()


async def user_id_for_telegram(telegram_id: int) -> int | None:
    if telegram_id in _user_ids:
        return _user_ids[telegram_id]
    async with get_async_session() as session:
        user = await identity.find_user(session, Provider.TELEGRAM, telegram_id)
    if user is not None:
        _user_ids[telegram_id] = user.id
        return user.id
    return None


def is_owner(telegram_id: int | None) -> bool:
    owner_id = get_settings().owner_id
    return owner_id is not None and telegram_id == owner_id


@dataclass(frozen=True)
class Actor:
    telegram_id: int
    user_id: int | None           # None — человек ещё не зарегистрирован
    is_owner: bool
    profile: StaffProfile | None

    @property
    def is_manager(self) -> bool:
        return self.is_owner or bool(self.profile and self.profile.is_manager)

    @property
    def shop_scope(self) -> int | None:
        """Магазин, в пределах которого действует менеджер; None — все магазины (владелец платформы)."""
        if self.is_owner:
            return None
        return self.profile.shop_id if self.profile else None

    async def work_shop_id(self) -> int | None:
        """Магазин, в котором создаются товары и рассылки: свой у менеджера, витрина — у владельца."""
        if self.profile and self.profile.shop_id:
            return self.profile.shop_id
        if self.is_owner:
            async with get_async_session() as session:
                return await shops.storefront_shop_id(session)
        return None


async def get_actor(update: Update) -> Actor | None:
    tg_user = update.effective_user
    if tg_user is None:
        return None
    user_id = await user_id_for_telegram(tg_user.id)
    profile = await get_staff_profile(user_id) if user_id is not None else None
    return Actor(telegram_id=tg_user.id, user_id=user_id, is_owner=is_owner(tg_user.id), profile=profile)


async def staff_chat_shop_id(update: Update) -> int | None:
    """Магазин, служебный чат которого — текущий чат (нажатие кнопки в группе продавцов)."""
    chat = update.effective_chat
    if chat is None:
        return None
    async with get_async_session() as session:
        return await shops.shop_for_staff_channel(session, Provider.TELEGRAM, chat.id)


async def can_manage_shop(update: Update, shop_id: int) -> bool:
    """Может ли автор апдейта действовать от имени магазина (заказы, товары, рассылки)."""
    actor = await get_actor(update)
    if actor and (actor.is_owner or (actor.profile and actor.profile.is_manager and actor.profile.shop_id == shop_id)):
        return True
    return await staff_chat_shop_id(update) == shop_id


async def is_staff(update: Update) -> bool:
    """Грубая проверка на входе: менеджер/владелец или служебный чат какого-либо магазина.
    Какой именно магазин — хендлер проверяет через can_manage_shop, загрузив заказ."""
    actor = await get_actor(update)
    return bool(actor and actor.is_manager) or await staff_chat_shop_id(update) is not None


async def deny(update: Update, handler_name: str):
    structured_logger.warning(
        "Access denied",
        action="access_denied",
        context={
            "handler": handler_name,
            "chat_id": update.effective_chat.id if update.effective_chat else None,
            "callback_data": update.callback_query.data if update.callback_query else None,
        },
    )
    if update.callback_query:
        await update.callback_query.answer(DENIED_TEXT, show_alert=True)
    elif update.effective_chat:
        await update.effective_chat.send_message(DENIED_TEXT)
    return ConversationHandler.END


def _guard(check):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not await check(update):
                return await deny(update, func.__name__)
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


async def _owner_check(update: Update) -> bool:
    return is_owner(update.effective_user.id if update.effective_user else None)


async def _manager_check(update: Update) -> bool:
    actor = await get_actor(update)
    return bool(actor and actor.is_manager)


owner_only = _guard(_owner_check)
owner_only.__doc__ = "Хендлер доступен только владельцу платформы (OWNER_ID)."
manager_only = _guard(_manager_check)
manager_only.__doc__ = "Хендлер доступен менеджерам магазинов и владельцу платформы."
staff_only = _guard(is_staff)
staff_only.__doc__ = "Хендлер доступен менеджерам и служебным чатам магазинов (магазин проверяется дальше)."
