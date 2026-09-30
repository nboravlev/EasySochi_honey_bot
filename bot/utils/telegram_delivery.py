"""Адаптер очереди уведомлений для Telegram: отображение нейтрального сообщения и отправка.

Вызывается через фасад utils.delivery (он же раздаёт строки другим платформам). Бот заблокирован
или чата нет — строка failed; сбой сети или лимит Telegram — повтор позже. Исключения наружу не выходят.
"""
import asyncio
from datetime import timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, ChatMigrated, Forbidden, RetryAfter

from db.db_async import get_async_session
from db.models import Notification
from domain.enums import Provider
from domain.messages import OutMessage
from services import notifications, shops
from services.notifications import Delivery
from utils.logging_config import structured_logger

def render(message: OutMessage) -> dict:
    """Нейтральное сообщение → параметры Bot.send_message."""
    kwargs: dict = {"text": message.text, "parse_mode": ParseMode.HTML}
    if message.buttons:
        kwargs["reply_markup"] = InlineKeyboardMarkup([
            [InlineKeyboardButton(b.text, callback_data=b.action) if b.action else InlineKeyboardButton(b.text, url=b.url)
             for b in row]
            for row in message.buttons
        ])
    return kwargs


def _seconds(value: int | float | timedelta) -> timedelta:
    return value if isinstance(value, timedelta) else timedelta(seconds=value)


async def _send_one(bot: Bot, session, row: Notification) -> str:
    """Отправить строку, записать результат. Возвращает sent / queued / failed."""
    try:
        sent = await bot.send_message(chat_id=int(row.address), **render(OutMessage.from_payload(row.payload)))
    except ChatMigrated as exc:
        # группу продавцов превратили в супергруппу: у неё новый ID — запоминаем и шлём туда
        row.address = str(exc.new_chat_id)
        if row.shop_id is not None:
            await shops.set_staff_channel(session, row.shop_id, Provider.TELEGRAM, exc.new_chat_id)
        notifications.mark_retry(row, str(exc), delay=timedelta(0))
        outcome = "queued"
    except RetryAfter as exc:
        outcome = "queued" if notifications.mark_retry(row, str(exc), delay=_seconds(exc.retry_after)) else "failed"
    except (Forbidden, BadRequest) as exc:
        # бот заблокирован, чат не найден, сообщение некорректно — повтор не поможет
        notifications.mark_failed(row, f"{type(exc).__name__}: {exc}")
        outcome = "failed"
    except Exception as exc:  # тайм-ауты и сетевые ошибки: Telegram из РФ отвечает нестабильно
        outcome = "queued" if notifications.mark_retry(row, f"{type(exc).__name__}: {exc}") else "failed"
    else:
        notifications.mark_sent(row, sent.message_id)
        return "sent"

    structured_logger.warning(
        "Telegram notification not delivered", action="notify_failed",
        context={"notification_id": row.id, "kind": row.kind, "user_id": row.user_id, "shop_id": row.shop_id,
                 "attempts": row.attempts, "will_retry": outcome == "queued", "error": row.last_error},
    )
    return outcome


async def deliver(bot: Bot, notification_ids: list[int], *, pace: float = 0.0) -> Delivery:
    """Отправить строки очереди сейчас; каждая — в своей транзакции под блокировкой строки."""
    result = Delivery()
    for i, notification_id in enumerate(notification_ids):
        if pace and i:
            await asyncio.sleep(pace)
        async with get_async_session() as session:
            row = await notifications.claim(session, notification_id, Provider.TELEGRAM)
            if row is None:
                continue  # уже отправлена, отправляется другим процессом или другая платформа
            outcome = await _send_one(bot, session, row)
            await session.commit()
        result.record(outcome)
    return result

