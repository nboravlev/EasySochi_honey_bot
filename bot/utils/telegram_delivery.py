"""Доставка уведомлений из очереди (services.notifications) в Telegram.

Хендлеры ставят сообщение в очередь — либо своей сессией вместе с изменением данных
(notifications.enqueue + после commit deliver), либо одним вызовом notify — и сразу пытаются
отправить. Что не ушло из-за сбоя Telegram, повторяет dispatch_due_job; бот заблокирован или
чата нет — строка помечается failed. Исключения наружу не выходят.
"""
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, ChatMigrated, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from db.db_async import get_async_session
from db.models import Notification
from domain.enums import Provider
from domain.messages import OutMessage, Recipient, ToShopStaff
from services import notifications, shops
from utils.logging_config import structured_logger

# Telegram: не больше ~30 сообщений в секунду от бота
SEND_INTERVAL_SEC = 0.05
DISPATCH_INTERVAL_SEC = 30
DISPATCH_BATCH = 100


@dataclass
class Delivery:
    """Итог немедленной отправки: отправлено / ждёт повтора / не будет доставлено."""
    sent: int = 0
    queued: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.sent > 0


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
        setattr(result, outcome, getattr(result, outcome) + 1)
    return result


async def notify(bot: Bot, to: Recipient, message: OutMessage, kind: str) -> Delivery:
    """Поставить в очередь отдельной транзакцией и сразу отправить."""
    async with get_async_session() as session:
        notification_ids = notifications.ids_of(await notifications.enqueue(session, to, message, kind))
        await session.commit()
    if not notification_ids:
        log_no_channel(to, kind)
    return await deliver(bot, notification_ids)


def log_no_channel(to: Recipient, kind: str) -> None:
    recipient = {"shop_id": to.shop_id} if isinstance(to, ToShopStaff) else {"user_id": to.user_id}
    structured_logger.warning(
        "Recipient has no Telegram channel", action="notify_no_channel", context={"kind": kind, **recipient},
    )


def undelivered_note(delivery: Delivery, who: str = "Покупатель") -> str:
    """Приписка для продавца, если уведомление не ушло сразу."""
    if delivery.ok:
        return ""
    if delivery.queued:
        return f"\n⏳ {who} пока не получил уведомление: Telegram не ответил, бот повторит отправку."
    return f"\n⚠️ {who} не получил уведомление (возможно, заблокировал бота)."


async def dispatch_due_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повторная отправка: всё, что не ушло сразу и чьё время пришло."""
    async with get_async_session() as session:
        due = await notifications.due_ids(session, Provider.TELEGRAM, limit=DISPATCH_BATCH)
    if not due:
        return
    result = await deliver(context.bot, due, pace=SEND_INTERVAL_SEC)
    structured_logger.info(
        "Notification retries processed", action="notify_retry_batch",
        context={"due": len(due), "sent": result.sent, "queued": result.queued, "failed": result.failed},
    )


async def purge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with get_async_session() as session:
        removed = await notifications.purge(session)
        await session.commit()
    if removed:
        structured_logger.info("Old notifications purged", action="notify_purge", context={"removed": removed})
