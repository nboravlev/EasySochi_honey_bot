"""Очередь уведомлений без БД: нейтральный формат, политика повторов, реакция на ошибки Telegram."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, ChatMigrated, Forbidden, RetryAfter, TimedOut

from db.models import Notification
from domain.enums import NotificationStatus
from domain.messages import Button, OutMessage
from services import notifications
from utils import telegram_delivery
from utils.delivery import Delivery, undelivered_note
from utils.telegram_delivery import render
from utils.timeutils import utcnow

MESSAGE = OutMessage("<b>Заказ</b>", [[Button("Карта", action="show_map_1"), Button("Сайт", url="https://x.ru")]])


def test_payload_round_trip():
    payload = MESSAGE.to_payload()
    assert payload == {"text": "<b>Заказ</b>", "buttons": [[{"text": "Карта", "action": "show_map_1"},
                                                           {"text": "Сайт", "url": "https://x.ru"}]]}
    assert OutMessage.from_payload(payload) == MESSAGE
    assert OutMessage("просто текст").to_payload() == {"text": "просто текст"}


def test_button_needs_exactly_one_target():
    with pytest.raises(ValueError):
        Button("ни туда ни сюда")
    with pytest.raises(ValueError):
        Button("и туда и сюда", action="a", url="https://x.ru")


def test_render_for_telegram():
    kwargs = render(MESSAGE)
    assert kwargs["parse_mode"] == "HTML" and kwargs["text"] == "<b>Заказ</b>"
    markup: InlineKeyboardMarkup = kwargs["reply_markup"]
    first, second = markup.inline_keyboard[0]
    assert first.callback_data == "show_map_1" and second.url == "https://x.ru"
    assert "reply_markup" not in render(OutMessage("без кнопок"))


def _row(**kw) -> Notification:
    return Notification(id=1, kind="test", provider="telegram", address="5001", payload=MESSAGE.to_payload(),
                        status=NotificationStatus.PENDING, attempts=0, next_attempt_at=utcnow(), **kw)


def test_retry_backoff_then_give_up():
    row = _row()
    before = utcnow()
    assert notifications.mark_retry(row, "timeout")
    assert row.attempts == 1 and row.status == NotificationStatus.PENDING
    assert row.next_attempt_at - before >= notifications.RETRY_DELAYS[0]

    for _ in range(notifications.MAX_ATTEMPTS - 2):
        assert notifications.mark_retry(row, "timeout")
    assert not notifications.mark_retry(row, "timeout")      # попытки исчерпаны
    assert row.status == NotificationStatus.FAILED and row.attempts == notifications.MAX_ATTEMPTS


def test_retry_after_explicit_delay_and_error_is_truncated():
    row = _row()
    notifications.mark_retry(row, "x" * 10_000, delay=timedelta(0))
    assert row.next_attempt_at <= utcnow() and len(row.last_error) == notifications.ERROR_MAX_LENGTH


class FakeBot:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.sent = []

    async def send_message(self, chat_id, **kwargs):
        if self.error:
            raise self.error
        self.sent.append((chat_id, kwargs))
        return SimpleNamespace(message_id=77)


@pytest.mark.parametrize(
    ("error", "outcome", "status"),
    [
        (None, "sent", NotificationStatus.SENT),
        (Forbidden("bot was blocked by the user"), "failed", NotificationStatus.FAILED),
        (BadRequest("Chat not found"), "failed", NotificationStatus.FAILED),
        (TimedOut(), "queued", NotificationStatus.PENDING),
        (RetryAfter(15), "queued", NotificationStatus.PENDING),
        (RuntimeError("что-то странное"), "queued", NotificationStatus.PENDING),
    ],
)
async def test_send_one_classifies_telegram_errors(error, outcome, status):
    bot, row = FakeBot(error), _row()
    assert await telegram_delivery._send_one(bot, None, row) == outcome
    assert row.status == status and row.attempts == 1
    if outcome == "sent":
        assert bot.sent[0][0] == 5001 and row.external_message_id == "77"
    if isinstance(error, RetryAfter):
        assert row.next_attempt_at - utcnow() > timedelta(seconds=10)


async def test_chat_migrated_switches_address():
    row = _row()          # личное уведомление: shop_id нет, канал магазина не трогаем
    assert await telegram_delivery._send_one(FakeBot(ChatMigrated(-1009)), None, row) == "queued"
    assert row.address == "-1009" and row.status == NotificationStatus.PENDING and row.next_attempt_at <= utcnow()


def test_undelivered_note():
    assert undelivered_note(Delivery(sent=1)) == ""
    assert "повторит" in undelivered_note(Delivery(queued=1))
    assert "заблокировал" in undelivered_note(Delivery(failed=1), who="Гость")
    assert "Гость" in undelivered_note(Delivery(), who="Гость")


async def test_rows_nobody_took_count_as_queued(monkeypatch):
    """Telegram недоступен (bot=None) — строки ждут повтора, продавцу не пишем «не доставлено»."""
    from utils import delivery, vk_delivery

    monkeypatch.setattr(vk_delivery, "client", lambda: None)
    result = await delivery.deliver(None, [1, 2])
    assert (result.sent, result.queued, result.failed) == (0, 2, 0)
    assert "повторит" in undelivered_note(result)
