"""VK: подпись параметров запуска Mini App и отображение/отправка уведомлений (без БД)."""
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import httpx
import pytest

from api.vk_auth import InvalidLaunchParams, sign_launch_params, validate_launch_params
from db.models import Notification
from domain.enums import NotificationStatus
from domain.messages import Button, OutMessage
from utils import vk_delivery
from utils.timeutils import utcnow

SECRET = "wvl68m4dR1UpLrVRli"
APP_ID = 6736218
DAY = 24 * 3600


def launch(secret: str = SECRET, ts: float | None = None, **extra) -> str:
    params = {
        "vk_app_id": str(APP_ID), "vk_user_id": "494075", "vk_ts": str(int(ts if ts is not None else time.time())),
        "vk_platform": "mobile_android", "vk_are_notifications_enabled": "1", "vk_language": "ru", **extra,
    }
    return sign_launch_params(params, secret)


def test_signature_matches_vk_algorithm():
    # как в документации VK: HMAC-SHA256 от отсортированных vk_*, base64 без «=», +/ → -_
    query = "vk_user_id=494075&vk_app_id=6736218&vk_ts=1&utm=1"
    vk = "vk_app_id=6736218&vk_ts=1&vk_user_id=494075"
    expected = base64.b64encode(hmac.new(SECRET.encode(), vk.encode(), hashlib.sha256).digest()).decode()
    expected = expected.rstrip("=").replace("+", "-").replace("/", "_")
    user = validate_launch_params(f"{query}&sign={expected}", SECRET, APP_ID, max_age_seconds=10**10, now=2)
    assert user.id == 494075


def test_valid_launch_params_with_leading_question_mark():
    user = validate_launch_params("?" + launch(), SECRET, APP_ID, DAY)
    assert (user.id, user.notifications_enabled, user.platform) == (494075, True, "mobile_android")


def test_non_vk_params_do_not_affect_signature():
    assert validate_launch_params(launch() + "&utm_source=ads", SECRET, APP_ID, DAY).id == 494075


@pytest.mark.parametrize("query", [
    launch(secret="other-secret"),
    launch().replace("vk_user_id=494075", "vk_user_id=1"),
    launch(ts=time.time() - 2 * DAY),
    launch(vk_app_id="1"),
    "", "sign=abc", "garbage",
])
def test_invalid_launch_params(query):
    with pytest.raises(InvalidLaunchParams):
        validate_launch_params(query, SECRET, APP_ID, DAY)


# --- уведомления

def test_plain_text_for_vk():
    text = 'Заказ <b>№5</b> «Мёд &lt;горный&gt;»\n<a href="https://x.ru">сайт</a>, <a href="https://y.ru">https://y.ru</a>'
    assert vk_delivery.to_plain_text(text) == "Заказ №5 «Мёд <горный>»\nсайт (https://x.ru), https://y.ru"


def test_render_replaces_bot_actions_with_storefront_link():
    message = OutMessage("Готов", [[Button("🟢 сегодня", action="pickup_today_5"), Button("Карта", url="https://maps")]])
    text, keyboard = vk_delivery.render(message, "https://vk.com/app1")
    assert text == "Готов"
    assert keyboard == {"inline": True, "buttons": [
        [{"action": {"type": "open_link", "link": "https://maps", "label": "Карта"}}],
        [{"action": {"type": "open_link", "link": "https://vk.com/app1", "label": "🍯 Открыть витрину"}}],
    ]}
    assert vk_delivery.render(OutMessage("Текст"), None) == ("Текст", None)


def row() -> Notification:
    return Notification(id=42, kind="test", provider="vk", address="494075", payload=OutMessage("<b>Привет</b>").to_payload(),
                        status=NotificationStatus.PENDING, attempts=0, next_attempt_at=utcnow())


def vk_client(response: dict, calls: list | None = None) -> vk_delivery.VkClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(dict(parse_qsl(request.content.decode())))
        return httpx.Response(200, json=response)

    return vk_delivery.VkClient("token", transport=httpx.MockTransport(handler))


async def test_send_uses_notification_id_as_random_id():
    calls: list[dict] = []
    notification = row()
    assert await vk_delivery._send_one(vk_client({"response": 777}, calls), notification) == "sent"
    [sent] = calls
    assert (sent["peer_id"], sent["random_id"], sent["message"], sent["v"]) == ("494075", "42", "Привет", "5.199")
    assert "keyboard" not in sent or json.loads(sent["keyboard"])["inline"]
    assert notification.status == NotificationStatus.SENT and notification.external_message_id == "777"


@pytest.mark.parametrize(("code", "outcome", "status"), [
    (901, "failed", NotificationStatus.FAILED),     # человек не разрешил сообщения от сообщества
    (9, "queued", NotificationStatus.PENDING),      # flood control — позже
    (10, "queued", NotificationStatus.PENDING),     # внутренняя ошибка VK
])
async def test_vk_errors(code, outcome, status):
    notification = row()
    client = vk_client({"error": {"error_code": code, "error_msg": "x"}})
    assert await vk_delivery._send_one(client, notification) == outcome
    assert notification.status == status and "VK API" in notification.last_error
