"""Доставка уведомлений из очереди (services.notifications) во все подключённые платформы.

Хендлеры и API ставят сообщение в очередь — своей сессией вместе с изменением данных
(notifications.enqueue + после commit deliver) или одним вызовом notify — и сразу пытаются отправить.
Каждая строка очереди адресована одной платформе; её забирает свой адаптер (telegram_delivery,
vk_delivery), чужие строки он пропускает. Что не ушло сразу, повторяет dispatch_due_job.
"""
from telegram import Bot
from telegram.ext import ContextTypes

from db.db_async import get_async_session
from domain.enums import Provider
from domain.messages import OutMessage, Recipient, ToShopStaff
from services import notifications
from services.notifications import Delivery
from utils import telegram_delivery, vk_delivery
from utils.logging_config import structured_logger

# Telegram: не больше ~30 сообщений в секунду от бота; VK — ~20 в секунду от сообщества
SEND_INTERVAL_SEC = 0.05
DISPATCH_INTERVAL_SEC = 30
DISPATCH_BATCH = 100

__all__ = ["Delivery", "deliver", "notify", "undelivered_note", "log_no_channel", "dispatch_due_job", "purge_job"]


async def deliver(bot: Bot | None, notification_ids: list[int], *, pace: float = 0.0) -> Delivery:
    """Отправить строки очереди сейчас. bot=None — Telegram недоступен: его строки дошлёт бот позже."""
    if not notification_ids:
        return Delivery()
    result = Delivery()
    if bot is not None:
        result += await telegram_delivery.deliver(bot, notification_ids, pace=pace)
    vk = vk_delivery.client()
    if vk is not None:
        result += await vk_delivery.deliver(vk, notification_ids, pace=pace)
    # строки, которые сейчас никто не взял (Telegram недоступен, строку отправляет другой процесс),
    # остались в очереди — их дошлёт повтор; это «ждёт», а не «не доставлено»
    result.queued += len(notification_ids) - (result.sent + result.queued + result.failed)
    return result


async def notify(bot: Bot | None, to: Recipient, message: OutMessage, kind: str) -> Delivery:
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
        "Recipient has no notification channel", action="notify_no_channel", context={"kind": kind, **recipient},
    )


def undelivered_note(delivery: Delivery, who: str = "Покупатель") -> str:
    """Приписка для продавца, если уведомление не ушло сразу."""
    if delivery.ok:
        return ""
    if delivery.queued:
        return f"\n⏳ {who} пока не получил уведомление: мессенджер не ответил, бот повторит отправку."
    return f"\n⚠️ {who} не получил уведомление (возможно, заблокировал бота или запретил сообщения)."


async def dispatch_due_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повторная отправка: всё, что не ушло сразу и чьё время пришло, — по платформам."""
    providers = [Provider.TELEGRAM] + ([Provider.VK] if vk_delivery.client() else [])
    for provider in providers:
        async with get_async_session() as session:
            due = await notifications.due_ids(session, provider, limit=DISPATCH_BATCH)
        if not due:
            continue
        result = await deliver(context.bot if provider == Provider.TELEGRAM else None, due, pace=SEND_INTERVAL_SEC)
        structured_logger.info(
            "Notification retries processed", action="notify_retry_batch",
            context={"provider": provider, "due": len(due), "sent": result.sent, "queued": result.queued,
                     "failed": result.failed},
        )


async def purge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with get_async_session() as session:
        removed = await notifications.purge(session)
        await session.commit()
    if removed:
        structured_logger.info("Old notifications purged", action="notify_purge", context={"removed": removed})
