"""Уведомления из API: немедленная доставка из очереди во все платформы и ссылка на бота.

Если Telegram недоступен при старте или отправке, API работает дальше: его уведомления остаются
в очереди, их дошлёт бот (utils.delivery.dispatch_due_job). VK-уведомления уходят через сообщество.
"""
import asyncio

from telegram import Bot
from telegram.request import BaseRequest

from utils import vk_delivery
from utils.delivery import deliver
from utils.logging_config import structured_logger


class Notifier:
    def __init__(self, token: str, request: BaseRequest | None = None):
        self._bot = Bot(token, request=request)
        self._ready = False
        self._lock = asyncio.Lock()

    async def bot(self) -> Bot | None:
        if not self._ready:
            async with self._lock:
                if not self._ready:
                    try:
                        await self._bot.initialize()
                        self._ready = True
                    except Exception as exc:
                        structured_logger.warning(
                            "Telegram is not reachable from API", action="api_telegram_unavailable",
                            context={"error": f"{type(exc).__name__}: {exc}"},
                        )
                        return None
        return self._bot

    async def bot_url(self) -> str | None:
        bot = await self.bot()
        return f"https://t.me/{bot.username}" if bot else None

    async def deliver(self, notification_ids: list[int]) -> None:
        """Фоновая задача после ответа клиенту: отправить только что поставленные уведомления."""
        if not notification_ids:
            return
        try:
            await deliver(await self.bot(), notification_ids)
        except Exception as exc:  # строки остались pending — дошлёт бот
            structured_logger.error("API notification delivery failed", action="api_deliver_failed", exception=exc)

    async def close(self) -> None:
        if self._ready:
            await self._bot.shutdown()
        vk = vk_delivery.client()
        if vk is not None:
            await vk.close()
            vk_delivery.set_client(None)
