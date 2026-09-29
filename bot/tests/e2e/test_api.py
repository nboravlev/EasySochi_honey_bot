"""HTTP API витрины на реальной БД: каталог, вход через Telegram, заказ из Mini App и его путь через бота."""
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from api.main import create_app
from api.telegram_auth import sign_init_data
from config import get_settings
from domain.enums import OrderStatus
from services import media, orders

from .conftest import (
    ADMIN_CHAT_ID,
    ADMIN_CHAT_MEMBER,
    BUYER,
    STRANGER,
    create_second_shop,
    execute,
    query,
    user_value,
)
from .harness import FakeTelegram, Person, all_text, button, to

pytestmark = pytest.mark.db


def tma(person: Person, age_seconds: int = 0) -> dict[str, str]:
    """Заголовок, который отправляет Mini App: initData, подписанная токеном бота."""
    fields = {
        "query_id": "AAE",
        "auth_date": str(int(time.time()) - age_seconds),
        "user": json.dumps({**person.as_dict(), "allows_write_to_pm": True}, ensure_ascii=False),
    }
    return {"Authorization": f"tma {sign_init_data(fields, get_settings().bot_token)}"}


@pytest.fixture
async def api(catalog):
    telegram = FakeTelegram()
    app = create_app(telegram_request=telegram, configure_logging=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, telegram=telegram)


async def test_public_catalog(api, catalog):
    response = await api.client.get("/api/catalog")
    assert response.status_code == 200 and "max-age" in response.headers["cache-control"]
    data = response.json()
    assert data["shop"]["name"] == "KrasPolHoney"
    [location] = data["shop"]["locations"]
    assert location["address"].startswith("Красная Поляна") and round(location["latitude"], 2) == 43.67
    [product] = data["products"]
    assert product["name"] == "Горный мёд" and product["shop"]["id"] == catalog.shop_id
    assert product["offers"] == [{"id": catalog.product_size_id, "size": "1.0", "price": "1500.00"}]
    assert data["types"] == [product["type"]]

    config = (await api.client.get("/api/config")).json()
    assert config == {"bot_url": "https://t.me/honey_test_bot", "marketplace": False}


async def test_account_needs_telegram_signature(api):
    assert (await api.client.get("/api/me")).status_code == 401
    assert (await api.client.get("/api/me", headers={"Authorization": "tma user=1&hash=00"})).status_code == 401
    assert (await api.client.get("/api/me", headers=tma(BUYER, age_seconds=3 * 24 * 3600))).status_code == 401
    response = await api.client.post("/api/orders", json={"product_size_id": 1})
    assert response.status_code == 401 and "Telegram" in response.json()["detail"]


async def test_first_visit_creates_user_and_profile_update(api):
    me = (await api.client.get("/api/me", headers=tma(BUYER))).json()
    assert me["first_name"] == "Анна" and me["phone"] is None
    assert await user_value("id", BUYER) == me["id"]

    bad = await api.client.patch("/api/me", headers=tma(BUYER), json={"phone": "позвоните"})
    assert bad.status_code == 422
    me = (await api.client.patch("/api/me", headers=tma(BUYER), json={"phone": "+7 900 000-00-00"})).json()
    assert me["phone"] == "+7 900 000-00-00"


async def test_order_from_mini_app_goes_through_bot(api, bot, catalog):
    response = await api.client.post(
        "/api/orders", headers=tma(BUYER),
        json={"product_size_id": catalog.product_size_id, "quantity": 2, "comment": "К <обеду>"},
    )
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"]["code"] == "created" and order["total"] == "3000.00"
    assert order["pickup"]["address"].startswith("Красная Поляна")

    # продавцу — карточка с кнопками в служебный чат, покупателю — сообщение в чат бота
    staff = to(api.telegram.calls, ADMIN_CHAT_ID)
    assert f"Новый заказ #{order['id']}" in all_text(staff) and "К &lt;обеду&gt;" in all_text(staff)
    confirm = button(staff, "confirm_order_")
    assert f"заказ №{order['id']} создан" in all_text(to(api.telegram.calls, BUYER.id))

    # дальше — как обычный заказ: продавец подтверждает в боте, покупатель видит статус в Mini App
    calls = await bot.click(ADMIN_CHAT_MEMBER, confirm, chat_id=ADMIN_CHAT_ID)
    assert "подтвержден" in all_text(to(calls, BUYER.id))
    [mine] = (await api.client.get("/api/orders", headers=tma(BUYER))).json()
    assert mine["id"] == order["id"] and mine["status"]["code"] == "processing"

    # чужие заказы не видны
    assert (await api.client.get("/api/orders", headers=tma(STRANGER))).json() == []


async def test_order_validation(api, catalog):
    headers = tma(BUYER)
    too_many = await api.client.post("/api/orders", headers=headers,
                                     json={"product_size_id": catalog.product_size_id, "quantity": 21})
    assert too_many.status_code == 422
    await execute("UPDATE product_sizes SET is_active = false WHERE id = :id", id=catalog.product_size_id)
    gone = await api.client.post("/api/orders", headers=headers, json={"product_size_id": catalog.product_size_id})
    assert gone.status_code == 409 and "не продаётся" in gone.json()["detail"]
    assert await query("SELECT count(*) FROM orders") == [(0,)]


async def test_storefront_does_not_sell_other_shops(api, catalog):
    shop_b = await create_second_shop(STRANGER)
    await execute(
        "INSERT INTO products (name, type_id, shop_id, is_active, is_draft) VALUES ('Чужой', :type_id, :shop, true, false)",
        type_id=catalog.type_id, shop=shop_b,
    )
    await execute(
        "INSERT INTO product_sizes (product_id, size_id, price, is_active) "
        "SELECT p.id, s.id, 900, true FROM products p, sizes s WHERE p.name = 'Чужой' AND s.name = 0.5",
    )
    [(other_size,)] = await query("SELECT ps.id FROM product_sizes ps JOIN products p ON p.id = ps.product_id "
                                  "WHERE p.name = 'Чужой'")
    catalog_names = [p["name"] for p in (await api.client.get("/api/catalog")).json()["products"]]
    assert catalog_names == ["Горный мёд"]
    response = await api.client.post("/api/orders", headers=tma(BUYER), json={"product_size_id": other_size})
    assert response.status_code == 409


async def test_order_rate_limit(api, catalog, monkeypatch):
    monkeypatch.setattr(orders, "MAX_ORDERS_PER_HOUR", 2)
    body = {"product_size_id": catalog.product_size_id}
    codes = [(await api.client.post("/api/orders", headers=tma(BUYER), json=body)).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    assert await query("SELECT count(*), sum(total_price) FROM orders WHERE status_id = :s",
                       s=OrderStatus.CREATED) == [(2, Decimal("3000.00"))]


async def test_media_is_served(api):
    key = media.storage().save(b"\xff\xd8jpeg", media.PRODUCTS)
    response = await api.client.get(f"/media/{key}")
    assert response.status_code == 200 and response.content == b"\xff\xd8jpeg"
    assert (await api.client.get("/media/../config.py")).status_code == 404
