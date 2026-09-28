"""Отправка сообщений в Telegram по внутренним идентификаторам: пользователю (users.id) и персоналу магазина.

Хендлеры не знают Telegram ID получателей — только users.id и shop_id; адрес в Telegram
находится здесь (user_identities, shop_channels). Отправка не бросает исключений: результат —
True/False, ошибка пишется в лог (покупатель мог заблокировать бота, у магазина может не быть чата).
"""
from telegram import Bot, Message

from db.db_async import get_async_session
from domain.enums import Provider
from services import identity, shops
from utils.logging_config import structured_logger


async def _send(bot: Bot, chat_id: str | int, what: str, **kwargs) -> Message | None:
    try:
        return await bot.send_message(chat_id=int(chat_id), **kwargs)
    except Exception as exc:
        structured_logger.warning(
            "Telegram message not delivered", action="notify_failed",
            context={"recipient": what, "error": str(exc)},
        )
        return None


async def telegram_chat_of_user(user_id: int) -> str | None:
    async with get_async_session() as session:
        return await identity.external_id(session, user_id, Provider.TELEGRAM)


async def send_to_user(bot: Bot, user_id: int, **kwargs) -> Message | None:
    """Личное сообщение человеку; None — нет Telegram-аккаунта или доставка не удалась."""
    chat_id = await telegram_chat_of_user(user_id)
    if chat_id is None:
        structured_logger.warning(
            "User has no Telegram account", action="notify_no_channel", context={"user_id": user_id}
        )
        return None
    return await _send(bot, chat_id, f"user:{user_id}", **kwargs)


async def send_to_shop_staff(bot: Bot, shop_id: int, **kwargs) -> Message | None:
    """Сообщение в служебный Telegram-чат магазина; None — чата нет или доставка не удалась."""
    async with get_async_session() as session:
        chat_id = await shops.staff_channel(session, shop_id, Provider.TELEGRAM)
    if chat_id is None:
        structured_logger.warning(
            "Shop has no Telegram staff chat", action="notify_no_channel", context={"shop_id": shop_id}
        )
        return None
    return await _send(bot, chat_id, f"shop:{shop_id}", **kwargs)
