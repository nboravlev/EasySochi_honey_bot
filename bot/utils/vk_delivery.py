"""Адаптер очереди уведомлений для ВКонтакте: сообщения покупателям от имени сообщества (messages.send).

Писать человеку сообщество может, только если он разрешил сообщения (витрина в VK спрашивает
разрешение перед первым заказом — VKWebAppAllowMessagesFromGroup). Кнопки-действия бота (callback)
в VK не работают — вместо них в сообщение добавляется ссылка на витрину («Мои заказы»).
random_id = ID уведомления: повторная отправка той же строки VK не продублирует.
"""
import asyncio
import html
import json
import re
from datetime import timedelta

import httpx

from config import get_settings
from db.db_async import get_async_session
from db.models import Notification
from domain.enums import Provider
from domain.messages import OutMessage
from services import notifications
from services.notifications import Delivery
from utils.logging_config import structured_logger

VK_API = "https://api.vk.com/method/"
VK_API_VERSION = "5.199"
BUTTON_LABEL_MAX = 40
MESSAGE_MAX = 4096

# коды ошибок VK API: повтор не поможет — человек запретил сообщения, в чёрном списке и т.п.
PERMANENT_ERRORS = {7, 15, 900, 901, 902, 911, 912, 913, 914, 917, 921, 936, 945, 946}
TOO_FAST = {6, 9}   # слишком много запросов / flood control


class VkApiError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"VK API {code}: {message}")


class VkClient:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._token = token
        self._http = httpx.AsyncClient(base_url=VK_API, timeout=15, transport=transport)

    async def call(self, method: str, **params) -> object:
        response = await self._http.post(method, data={**params, "access_token": self._token, "v": VK_API_VERSION})
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise VkApiError(int(body["error"].get("error_code", 0)), str(body["error"].get("error_msg", "")))
        return body.get("response")

    async def send_message(self, peer_id: int, text: str, keyboard: dict | None, random_id: int) -> object:
        params = {"peer_id": peer_id, "message": text, "random_id": random_id}
        if keyboard:
            params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
        return await self.call("messages.send", **params)

    async def close(self) -> None:
        await self._http.aclose()


_client: VkClient | None = None


def client() -> VkClient | None:
    """Клиент сообщества VK из настроек; None — сообщения в VK не настроены."""
    global _client
    settings = get_settings()
    if _client is None and settings.vk_messages_enabled:
        _client = VkClient(settings.vk_group_token)
    return _client


def set_client(value: VkClient | None) -> None:
    """Подмена клиента (тесты)."""
    global _client
    _client = value


def app_url() -> str | None:
    app_id = get_settings().vk_app_id
    return f"https://vk.com/app{app_id}" if app_id else None


# --- отображение

_LINK = re.compile(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def to_plain_text(text: str) -> str:
    """HTML-подмножество уведомлений → обычный текст (VK разметку не понимает)."""
    def link(match: re.Match) -> str:
        url, label = html.unescape(match.group(1)), _TAG.sub("", match.group(2))
        return label if not url or url == html.unescape(label) else f"{label} ({url})"

    return html.unescape(_TAG.sub("", _LINK.sub(link, text)))[:MESSAGE_MAX]


def render(message: OutMessage, storefront_url: str | None) -> tuple[str, dict | None]:
    """Текст и inline-клавиатура VK: кнопки-ссылки как есть, вместо кнопок-действий — ссылка на витрину."""
    rows = [
        [{"action": {"type": "open_link", "link": b.url, "label": b.text[:BUTTON_LABEL_MAX]}} for b in row if b.url]
        for row in message.buttons
    ]
    rows = [row for row in rows if row]
    if storefront_url:
        rows.append([{"action": {"type": "open_link", "link": storefront_url, "label": "🍯 Открыть витрину"}}])
    return to_plain_text(message.text), ({"inline": True, "buttons": rows} if rows else None)


# --- отправка

async def _send_one(vk: VkClient, row: Notification) -> str:
    text, keyboard = render(OutMessage.from_payload(row.payload), app_url())
    try:
        message_id = await vk.send_message(int(row.address), text, keyboard, random_id=row.id)
    except VkApiError as exc:
        if exc.code in PERMANENT_ERRORS:
            notifications.mark_failed(row, str(exc))
            outcome = "failed"
        else:
            delay = timedelta(seconds=2) if exc.code in TOO_FAST else None
            outcome = "queued" if notifications.mark_retry(row, str(exc), delay=delay) else "failed"
    except Exception as exc:  # сеть, тайм-аут, 5xx
        outcome = "queued" if notifications.mark_retry(row, f"{type(exc).__name__}: {exc}") else "failed"
    else:
        notifications.mark_sent(row, message_id if isinstance(message_id, int) else None)
        return "sent"

    structured_logger.warning(
        "VK notification not delivered", action="notify_failed",
        context={"provider": "vk", "notification_id": row.id, "kind": row.kind, "user_id": row.user_id,
                 "attempts": row.attempts, "will_retry": outcome == "queued", "error": row.last_error},
    )
    return outcome


async def deliver(vk: VkClient, notification_ids: list[int], *, pace: float = 0.0) -> Delivery:
    """Отправить VK-строки очереди сейчас; строки других платформ пропускаются."""
    result = Delivery()
    for notification_id in notification_ids:
        async with get_async_session() as session:
            row = await notifications.claim(session, notification_id, Provider.VK)
            if row is None:
                continue
            outcome = await _send_one(vk, row)
            await session.commit()
        result.record(outcome)
        if pace:
            await asyncio.sleep(pace)
    return result
