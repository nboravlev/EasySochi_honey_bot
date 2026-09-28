"""Сквозные тесты: настоящее приложение бота (все хендлеры, PTB, БД), но вместо Telegram — FakeTelegram.

FakeTelegram отвечает на вызовы Bot API правдоподобными объектами и записывает их, чтобы тест
мог проверить, что бот отправил, кому и с какими кнопками. Апдейты (сообщения, нажатия кнопок)
тест формирует сам и передаёт в Application.process_update — как это делает polling.
"""
import itertools
import json
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from telegram import Update
from telegram.error import TimedOut
from telegram.ext import Application
from telegram.request import BaseRequest, RequestData

BOT_USER = {"id": 999000, "is_bot": True, "first_name": "HoneyBot", "username": "honey_test_bot"}
MESSAGE_METHODS = {
    "sendMessage", "sendPhoto", "sendLocation", "editMessageText", "editMessageCaption", "editMessageReplyMarkup",
}


@dataclass
class Call:
    method: str
    params: dict[str, Any]

    @property
    def chat_id(self) -> int | None:
        value = self.params.get("chat_id")
        return int(value) if value is not None else None

    @property
    def text(self) -> str:
        return str(self.params.get("text") or self.params.get("caption") or "")

    @property
    def buttons(self) -> list[str]:
        markup = self.params.get("reply_markup") or {}
        if isinstance(markup, str):
            markup = json.loads(markup)
        return [b.get("callback_data") for row in markup.get("inline_keyboard", []) for b in row if b.get("callback_data")]


class FakeTelegram(BaseRequest):
    def __init__(self):
        self.calls: list[Call] = []
        self.blocked: set[int] = set()     # эти пользователи заблокировали бота (403)
        self.unreachable: set[int] = set() # в эти чаты Telegram не отвечает (тайм-аут)
        self._message_ids = itertools.count(10_000)

    @property
    def read_timeout(self) -> float | None:
        return None

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def do_request(self, url: str, method: str, request_data: RequestData | None = None, **_timeouts):
        api_method = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        chat_id = int(params.get("chat_id", 0) or 0)
        if api_method == "sendMessage" and chat_id in self.unreachable:
            raise TimedOut("fake timeout")
        if api_method == "sendMessage" and chat_id in self.blocked:
            error = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
            return 403, json.dumps(error).encode()
        self.calls.append(Call(api_method, params))
        return 200, json.dumps({"ok": True, "result": self._result(api_method, params)}).encode()

    def _result(self, api_method: str, params: dict[str, Any]) -> Any:
        if api_method == "getMe":
            return {**BOT_USER, "can_join_groups": True, "can_read_all_group_messages": False,
                    "supports_inline_queries": False}
        if api_method in MESSAGE_METHODS:
            chat_id = int(params.get("chat_id", 0))
            return {
                "message_id": int(params.get("message_id") or next(self._message_ids)),
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
                "from": BOT_USER,
                "text": str(params.get("text") or ""),
            }
        return True  # answerCallbackQuery, deleteMessage, setMyCommands, …


@dataclass
class Person:
    id: int
    first_name: str = "Анна"
    username: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "is_bot": False, "first_name": self.first_name}
        if self.username:
            data["username"] = self.username
        return data


@dataclass
class Bot:
    """Обёртка для теста: отправить сообщение / нажать кнопку и получить, что ответил бот."""
    app: Application
    telegram: FakeTelegram
    errors: list[BaseException] = field(default_factory=list)
    stopped: bool = False
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    async def _process(self, data: dict[str, Any]) -> list[Call]:
        before = len(self.telegram.calls)
        await self.app.process_update(Update.de_json(data, self.app.bot))
        assert not self.errors, f"handler raised: {self.errors[0]!r}"
        return self.telegram.calls[before:]

    def _chat(self, chat_id: int) -> dict[str, Any]:
        return {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"}

    async def send(self, person: Person, text: str, chat_id: int | None = None) -> list[Call]:
        message: dict[str, Any] = {
            "message_id": next(self._ids), "date": int(time.time()),
            "chat": self._chat(chat_id or person.id), "from": person.as_dict(), "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return await self._process({"update_id": next(self._ids), "message": message})

    async def click(self, person: Person, data: str, chat_id: int | None = None, message_id: int = 1) -> list[Call]:
        query = {
            "id": str(next(self._ids)), "from": person.as_dict(), "chat_instance": "test", "data": data,
            "message": {"message_id": message_id, "date": int(time.time()), "chat": self._chat(chat_id or person.id),
                        "from": BOT_USER, "text": "…"},
        }
        return await self._process({"update_id": next(self._ids), "callback_query": query})

    async def run_job(self, job) -> list[Call]:
        """Запустить периодическую задачу бота (как это делает JobQueue) и вернуть, что она отправила."""
        before = len(self.telegram.calls)
        await job(SimpleNamespace(bot=self.app.bot))
        return self.telegram.calls[before:]


def to(calls: list[Call], chat_id: int) -> list[Call]:
    """Сообщения, отправленные (или отредактированные) в указанный чат."""
    return [c for c in calls if c.method in MESSAGE_METHODS and c.chat_id == chat_id]


def all_text(calls: list[Call]) -> str:
    return "\n".join(c.text for c in calls if c.text)


def alerts(calls: list[Call]) -> list[str]:
    return [c.params.get("text", "") for c in calls if c.method == "answerCallbackQuery" and c.params.get("text")]


def button(calls: list[Call], prefix: str) -> str:
    for call in calls:
        for data in call.buttons:
            if data.startswith(prefix):
                return data
    raise AssertionError(f"нет кнопки {prefix!r} среди {[b for c in calls for b in c.buttons]}")
