"""ВКонтакте: вход в витрину из VK Mini App, заказ, уведомления покупателю от сообщества VK.

Настоящее приложение API и бота, PostgreSQL; вместо api.vk.com — httpx.MockTransport.
"""
import time
from types import SimpleNamespace
from urllib.parse import parse_qsl

import httpx
import pytest

from api.main import create_app
from api.vk_auth import sign_launch_params
from config import get_settings
from utils import vk_delivery

from .conftest import ADMIN_CHAT_ID, ADMIN_CHAT_MEMBER, query
from .harness import FakeTelegram, all_text, button, to

pytestmark = pytest.mark.db

VK_APP_ID = 51000001
VK_SECRET = "test-vk-secret"
VK_GROUP_ID = 22000002
VK_USER = 777888


def vk_auth(user_id: int = VK_USER) -> dict[str, str]:
    params = {"vk_app_id": str(VK_APP_ID), "vk_user_id": str(user_id), "vk_ts": str(int(time.time())),
              "vk_platform": "mobile_web", "vk_language": "ru"}
    return {"Authorization": f"vk {sign_launch_params(params, VK_SECRET)}"}


class FakeVk:
    """api.vk.com: записывает messages.send; blocked — пользователи, запретившие сообщения (ошибка 901)."""

    def __init__(self):
        self.sent: list[dict] = []
        self.blocked: set[int] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.content.decode()))
        if int(params["peer_id"]) in self.blocked:
            return httpx.Response(200, json={"error": {"error_code": 901, "error_msg": "Can't send messages"}})
        self.sent.append(params)
        return httpx.Response(200, json={"response": len(self.sent)})

    def texts(self, peer_id: int = VK_USER) -> str:
        return "\n".join(m["message"] for m in self.sent if int(m["peer_id"]) == peer_id)


@pytest.fixture
async def vk(catalog, monkeypatch):
    settings = get_settings()
    for name, value in {"vk_app_id": VK_APP_ID, "vk_app_secret": VK_SECRET,
                        "vk_group_id": VK_GROUP_ID, "vk_group_token": "group-token"}.items():
        monkeypatch.setattr(settings, name, value)
    fake = FakeVk()
    vk_delivery.set_client(vk_delivery.VkClient("group-token", transport=httpx.MockTransport(fake.handler)))
    telegram = FakeTelegram()
    app = create_app(telegram_request=telegram, configure_logging=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, telegram=telegram, fake=fake)
    vk_delivery.set_client(None)


async def test_config_tells_storefront_about_vk(vk):
    config = (await vk.client.get("/api/config")).json()
    assert config["vk_group_id"] == VK_GROUP_ID and config["vk_app_url"] == f"https://vk.com/app{VK_APP_ID}"


async def test_vk_login_creates_vk_user(vk):
    me = await vk.client.get("/api/me", headers=vk_auth())
    assert me.status_code == 200 and me.json()["first_name"] is None
    # имя приходит из VKWebAppGetUserInfo
    me = (await vk.client.patch("/api/me", headers=vk_auth(), json={"first_name": "Ольга"})).json()
    assert me["first_name"] == "Ольга"
    assert await query("SELECT provider, external_id FROM user_identities WHERE user_id = :id", id=me["id"]) == \
        [("vk", str(VK_USER))]

    forged = vk_auth()["Authorization"].replace(str(VK_USER), "1")
    assert (await vk.client.get("/api/me", headers={"Authorization": forged})).status_code == 401


async def test_order_from_vk_through_bot(vk, bot, catalog):
    await vk.client.patch("/api/me", headers=vk_auth(), json={"first_name": "Ольга", "phone": "+79000000000"})
    response = await vk.client.post("/api/orders", headers=vk_auth(),
                                    json={"product_size_id": catalog.product_size_id, "quantity": 1})
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    # продавцу — карточка в Telegram со ссылкой на профиль VK; покупателю — сообщение от сообщества VK
    staff = to(vk.telegram.calls, ADMIN_CHAT_ID)
    assert f"Новый заказ #{order_id}" in all_text(staff) and f"https://vk.com/id{VK_USER}" in all_text(staff)
    assert f"заказ №{order_id} создан" in vk.fake.texts()
    [placed] = vk.fake.sent
    assert "<" not in placed["message"] and f"vk.com/app{VK_APP_ID}" in placed["keyboard"]

    # продавец подтверждает в Telegram — уведомление уходит покупателю во ВКонтакте сразу
    calls = await bot.click(ADMIN_CHAT_MEMBER, button(staff, "confirm_order_"), chat_id=ADMIN_CHAT_ID)
    assert "подтвержден" in vk.fake.texts()
    assert "Покупатель не получил" not in all_text(calls)
    assert await query("SELECT provider, status FROM notifications WHERE kind = 'order_confirmed'") == [("vk", "sent")]


async def test_vk_user_without_message_permission(vk, bot, catalog):
    vk.fake.blocked.add(VK_USER)
    await vk.client.post("/api/orders", headers=vk_auth(), json={"product_size_id": catalog.product_size_id})
    staff = to(vk.telegram.calls, ADMIN_CHAT_ID)

    calls = await bot.click(ADMIN_CHAT_MEMBER, button(staff, "confirm_order_"), chat_id=ADMIN_CHAT_ID)
    assert "не получил уведомление" in all_text(to(calls, ADMIN_CHAT_ID))
    # запрет сообщений — повторять бессмысленно
    assert await query("SELECT status FROM notifications WHERE kind = 'order_confirmed'") == [("failed",)]
