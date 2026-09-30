"""Админка (/api/admin) на реальной БД: вход, права магазинов, заказы, товары, магазины, статистика, очередь."""
import json
from io import BytesIO
from urllib.parse import urlparse

import pytest
from PIL import Image as PILImage

from config import get_settings

from .conftest import (
    ADMIN_CHAT_ID,
    BUYER,
    MANAGER,
    OWNER,
    SHOP_B,
    STAFF_CHAT_B,
    STRANGER,
    create_second_shop,
    query,
    register,
    tma,
)
from .harness import all_text, to

pytestmark = pytest.mark.db

CSRF = {"X-Honey-Admin": "1"}
OTHER_MANAGER = STRANGER    # менеджер магазина Б


def jpeg() -> bytes:
    out = BytesIO()
    PILImage.new("RGB", (400, 300), (220, 160, 40)).save(out, format="JPEG")
    return out.getvalue()


async def place_order(api, catalog, person=BUYER, quantity: int = 1) -> int:
    response = await api.client.post("/api/orders", headers=tma(person),
                                     json={"product_size_id": catalog.product_size_id, "quantity": quantity})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def login_token(calls) -> str:
    """Токен из кнопки «Открыть админку» в ответе бота на /admin."""
    for call in calls:
        markup = call.params.get("reply_markup")
        markup = json.loads(markup) if isinstance(markup, str) else markup or {}
        for row in markup.get("inline_keyboard", []):
            for b in row:
                if b.get("url", "").count("#login="):
                    url = b["url"]
                    assert urlparse(url).path == "/admin/"
                    return url.split("#login=", 1)[1]
    raise AssertionError("нет ссылки входа в админку")


# --- вход


async def test_browser_login_via_bot_link(api, bot, catalog, monkeypatch):
    monkeypatch.setattr(get_settings(), "webapp_url", "https://honey.test/")
    calls = await bot.send(MANAGER, "/admin")
    assert "одноразовая" in all_text(calls)
    token = login_token(calls)

    # в группе ссылку не выдаём: её увидят все участники; посторонним — нет прав
    assert "только в личном чате" in all_text(await bot.send(MANAGER, "/admin", chat_id=ADMIN_CHAT_ID))
    assert "Недостаточно прав" in all_text(await bot.send(STRANGER, "/admin"))

    response = await api.client.post("/api/admin/login", json={"token": token})
    assert response.status_code == 200
    assert response.json()["shop"]["name"] == "KrasPolHoney" and not response.json()["is_owner"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie and "path=/api/admin" in cookie

    me = await api.client.get("/api/admin/me")
    assert me.status_code == 200 and me.json()["via"] == "session"
    # ссылка одноразовая
    assert (await api.client.post("/api/admin/login", json={"token": token})).status_code == 401
    # изменяющий запрос по cookie — только с заголовком админки (CSRF)
    assert (await api.client.post("/api/admin/logout")).status_code == 204   # выход без заголовка — можно
    assert (await api.client.get("/api/admin/me")).status_code == 401


async def test_csrf_header_required_for_cookie_changes(api, bot, catalog, monkeypatch):
    monkeypatch.setattr(get_settings(), "webapp_url", "https://honey.test/")
    token = login_token(await bot.send(MANAGER, "/admin"))
    await api.client.post("/api/admin/login", json={"token": token})
    order_id = await place_order(api, catalog)

    body = {"action": "confirm"}
    assert (await api.client.post(f"/api/admin/orders/{order_id}/actions", json=body)).status_code == 403
    response = await api.client.post(f"/api/admin/orders/{order_id}/actions", json=body, headers=CSRF)
    assert response.status_code == 200 and response.json()["order"]["status"]["code"] == "processing"


async def test_only_staff_gets_in(api, catalog):
    assert (await api.client.get("/api/admin/me")).status_code == 401
    assert (await api.client.get("/api/admin/me", headers=tma(BUYER))).status_code == 403
    me = (await api.client.get("/api/admin/me", headers=tma(MANAGER))).json()
    assert me["via"] == "telegram" and not me["is_owner"]
    owner = (await api.client.get("/api/admin/me", headers=tma(OWNER))).json()
    assert owner["is_owner"] and owner["shop"] is None


# --- заказы


async def test_order_actions_notify_like_bot(api, catalog):
    first, second = await place_order(api, catalog, quantity=2), await place_order(api, catalog)
    page = (await api.client.get("/api/admin/orders?group=new", headers=tma(MANAGER))).json()
    assert page["total"] == 2 and {o["id"] for o in page["items"]} == {first, second}
    card = next(o for o in page["items"] if o["id"] == first)
    assert card["customer"]["name"] == "Анна" and card["actions"] == ["confirm", "decline"]
    assert (await api.client.get(f"/api/admin/orders?q={first}", headers=tma(MANAGER))).json()["total"] == 1
    assert (await api.client.get("/api/admin/orders?q=анн", headers=tma(MANAGER))).json()["total"] == 2

    api.telegram.calls.clear()
    response = await api.client.post(f"/api/admin/orders/{first}/actions", headers=tma(MANAGER),
                                     json={"action": "confirm"})
    result = response.json()
    assert result["order"]["status"]["code"] == "processing" and result["order"]["manager"] == "Мария"
    assert result["customer_notified"]["sent"] == 1
    assert "подтвержден" in all_text(to(api.telegram.calls, BUYER.id))
    assert "подтверждён в админке (Мария)" in all_text(to(api.telegram.calls, ADMIN_CHAT_ID))

    again = await api.client.post(f"/api/admin/orders/{first}/actions", headers=tma(MANAGER), json={"action": "confirm"})
    assert again.status_code == 409

    declined = await api.client.post(f"/api/admin/orders/{second}/actions", headers=tma(MANAGER),
                                     json={"action": "decline", "reason": "Мёд <закончился>"})
    assert declined.json()["order"]["decline_reason"] == "Мёд <закончился>"
    assert "Мёд &lt;закончился&gt;" in all_text(to(api.telegram.calls, BUYER.id))


async def test_manager_sees_only_own_shop(api, catalog):
    order_id = await place_order(api, catalog)
    await create_second_shop(OTHER_MANAGER)
    other = tma(OTHER_MANAGER)
    assert (await api.client.get("/api/admin/orders", headers=other)).json()["total"] == 0
    assert (await api.client.get(f"/api/admin/orders/{order_id}", headers=other)).status_code == 404
    response = await api.client.post(f"/api/admin/orders/{order_id}/actions", headers=other, json={"action": "confirm"})
    assert response.status_code == 404
    assert (await api.client.get("/api/admin/products", headers=other)).json() == []
    # параметр shop_id менеджеру не помогает — всегда свой магазин
    assert (await api.client.get(f"/api/admin/orders?shop_id={catalog.shop_id}", headers=other)).json()["total"] == 0
    # владелец видит всё
    assert (await api.client.get("/api/admin/orders", headers=tma(OWNER))).json()["total"] == 1


# --- товары


async def test_product_lifecycle(api, catalog):
    headers = tma(MANAGER)
    reference = (await api.client.get("/api/admin/reference", headers=headers)).json()
    size = next(s for s in reference["sizes"] if s["kg"] == "0.5")

    created = await api.client.post("/api/admin/products", headers=headers, json={
        "name": "Липовый", "type_id": catalog.type_id, "description": "Светлый",
        "offers": [{"size_id": size["id"], "price": "900"}],
    })
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["state"] == "draft" and product["shop"]["id"] == catalog.shop_id
    public = [p["name"] for p in (await api.client.get("/api/catalog")).json()["products"]]
    assert "Липовый" not in public   # черновик покупатели не видят

    photo = await api.client.post(f"/api/admin/products/{product['id']}/photos", headers=headers,
                                  files={"file": ("honey.jpg", jpeg(), "image/jpeg")})
    [picture] = photo.json()["photos"]
    assert (await api.client.get(picture["url"])).status_code == 200
    bad = await api.client.post(f"/api/admin/products/{product['id']}/photos", headers=headers,
                                files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 422

    published = (await api.client.post(f"/api/admin/products/{product['id']}/publish", headers=headers)).json()
    assert published["state"] == "published"
    lipa = next(p for p in (await api.client.get("/api/catalog")).json()["products"] if p["name"] == "Липовый")
    assert lipa["photos"] == [picture["url"]] and lipa["offers"][0]["price"] == "900.00"

    offers = await api.client.put(f"/api/admin/products/{product['id']}/offers", headers=headers,
                                  json=[{"size_id": size["id"], "price": "950", "active": True}])
    assert offers.json()["offers"][0]["price"] == "950.00"
    empty = await api.client.put(f"/api/admin/products/{product['id']}/offers", headers=headers,
                                 json=[{"size_id": size["id"], "price": "950", "active": False}])
    assert empty.status_code == 422

    renamed = await api.client.patch(f"/api/admin/products/{product['id']}", headers=headers, json={"name": "Липа"})
    assert renamed.json()["name"] == "Липа"
    withdrawn = await api.client.post(f"/api/admin/products/{product['id']}/withdraw", headers=headers)
    assert withdrawn.json()["state"] == "withdrawn"
    assert "Липа" not in [p["name"] for p in (await api.client.get("/api/catalog")).json()["products"]]


async def test_withdraw_blocked_by_active_orders(api, catalog):
    order_id = await place_order(api, catalog)
    [product] = (await api.client.get("/api/admin/products", headers=tma(MANAGER))).json()
    response = await api.client.post(f"/api/admin/products/{product['id']}/withdraw", headers=tma(MANAGER))
    assert response.status_code == 409 and f"№{order_id}" in response.json()["detail"]


async def test_new_type_is_owner_only(api, catalog):
    assert (await api.client.post("/api/admin/types", headers=tma(MANAGER), json={"name": "Гречишный"})).status_code == 403
    created = await api.client.post("/api/admin/types", headers=tma(OWNER), json={"name": "Гречишный"})
    assert created.status_code == 201
    assert (await api.client.post("/api/admin/types", headers=tma(OWNER), json={"name": "Гречишный"})).status_code == 422


# --- магазины и менеджеры


async def test_owner_manages_shops_and_managers(api, bot, catalog):
    owner = tma(OWNER)
    assert (await api.client.post("/api/admin/shops", headers=tma(MANAGER),
                                  json={"slug": "x", "name": "X"})).status_code == 403
    [own] = (await api.client.get("/api/admin/shops", headers=tma(MANAGER))).json()
    assert own["is_storefront"] and own["staff_chat_id"] == str(ADMIN_CHAT_ID)

    shop = (await api.client.post("/api/admin/shops", headers=owner,
                                  json={"slug": SHOP_B, "name": "Магазин Б", "phone": "+7 900"})).json()
    assert (await api.client.post("/api/admin/shops", headers=owner,
                                  json={"slug": SHOP_B, "name": "Дубль"})).status_code == 409
    shop = (await api.client.post(f"/api/admin/shops/{shop['id']}/locations", headers=owner, json={
        "name": "Склад", "address": "Адлер, ул. Ленина, 1", "latitude": 43.43, "longitude": 39.92,
    })).json()
    [location] = shop["locations"]
    assert round(location["latitude"], 2) == 43.43 and round(location["longitude"], 2) == 39.92
    shop = (await api.client.put(f"/api/admin/shops/{shop['id']}/staff-chat", headers=owner,
                                 json={"telegram_chat_id": STAFF_CHAT_B})).json()
    assert shop["staff_chat_id"] == str(STAFF_CHAT_B)

    await register(BUYER)
    manager = await api.client.post("/api/admin/managers", headers=owner,
                                    json={"user": f"@{BUYER.username}", "shop_id": shop["id"]})
    assert manager.status_code == 201 and manager.json()["shop"]["name"] == "Магазин Б"
    assert "права менеджера магазина «Магазин Б»" in all_text(to(api.telegram.calls, BUYER.id))
    assert (await api.client.get("/api/admin/me", headers=tma(BUYER))).json()["shop"]["name"] == "Магазин Б"
    missing = await api.client.post("/api/admin/managers", headers=owner, json={"user": "@nobody", "shop_id": shop["id"]})
    assert missing.status_code == 404

    user_id = manager.json()["user_id"]
    assert (await api.client.delete(f"/api/admin/managers/{user_id}", headers=owner)).status_code == 204
    assert (await api.client.get("/api/admin/me", headers=tma(BUYER))).status_code == 403
    owner_id = (await api.client.get("/api/admin/me", headers=owner)).json()["user_id"]
    assert (await api.client.delete(f"/api/admin/managers/{owner_id}", headers=owner)).status_code == 409


async def test_removed_manager_loses_browser_session(api, bot, catalog, monkeypatch):
    monkeypatch.setattr(get_settings(), "webapp_url", "https://honey.test/")
    await api.client.post("/api/admin/login", json={"token": login_token(await bot.send(MANAGER, "/admin"))})
    assert (await api.client.get("/api/admin/me")).status_code == 200
    manager_id = (await api.client.get("/api/admin/me")).json()["user_id"]
    await api.client.delete(f"/api/admin/managers/{manager_id}", headers=tma(OWNER))
    assert (await api.client.get("/api/admin/me")).status_code == 401


# --- статистика и очередь


async def test_stats(api, catalog):
    order_id = await place_order(api, catalog, quantity=2)
    await api.client.post(f"/api/admin/orders/{order_id}/actions", headers=tma(MANAGER), json={"action": "confirm"})
    stats = (await api.client.get("/api/admin/stats?days=30", headers=tma(MANAGER))).json()
    assert stats["in_progress"] == {"count": 1, "total": "3000.00"}
    assert stats["sales"] == [{"name": "Горный мёд", "kg": "2.0", "total": "3000.00"}]
    assert (await api.client.get("/api/admin/stats?days=5", headers=tma(MANAGER))).status_code == 422


async def test_failed_notifications_can_be_retried(api, catalog):
    order_id = await place_order(api, catalog)
    api.telegram.blocked.add(BUYER.id)
    result = (await api.client.post(f"/api/admin/orders/{order_id}/actions", headers=tma(MANAGER),
                                    json={"action": "confirm"})).json()
    assert result["customer_notified"] == {"sent": 0, "queued": 0, "failed": 1}

    assert (await api.client.get("/api/admin/notifications", headers=tma(MANAGER))).status_code == 403
    [failed] = (await api.client.get("/api/admin/notifications?status=failed", headers=tma(OWNER))).json()
    assert failed["kind"] == "order_confirmed" and "подтвержден" in failed["text"] and "<" not in failed["text"]

    api.telegram.blocked.clear()      # покупатель разблокировал бота
    retry = await api.client.post(f"/api/admin/notifications/{failed['id']}/retry", headers=tma(OWNER))
    assert retry.json()["sent"] == 1
    assert await query("SELECT status FROM notifications WHERE id = :id", id=failed["id"]) == [("sent",)]
