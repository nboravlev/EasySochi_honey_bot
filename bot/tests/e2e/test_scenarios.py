"""Сквозные сценарии: как их проходят люди в Telegram."""
from datetime import timedelta

import pytest

from domain.enums import OrderStatus, Role, TastingStatus
from utils.timeutils import local_today

from .conftest import (
    ADMIN_CHAT_ID,
    ADMIN_CHAT_MEMBER,
    BUYER,
    MANAGER,
    OWNER,
    SHOP_B,
    STAFF_CHAT_B,
    STRANGER,
    create_second_shop,
    query,
    register,
    start_bot,
    stop_bot,
    user_value,
)
from .harness import alerts, all_text, button, to

pytestmark = pytest.mark.db


async def order_status(order_id: int) -> int:
    return (await query("SELECT status_id FROM orders WHERE id = :id", id=order_id))[0][0]


async def place_order(bot, catalog, quantity: int = 1) -> int:
    """Покупатель: каталог → сорт → размер → количество → «Заказать». Возвращает ID заказа."""
    calls = await bot.click(BUYER, "honey_buy")
    calls = await bot.click(BUYER, button(calls, f"product_type_{catalog.type_id}"))
    calls = await bot.click(BUYER, button(calls, f"select_size_{catalog.product_size_id}"))
    pay = button(calls, "pay_")
    for _ in range(quantity - 1):
        calls = await bot.click(BUYER, button(calls, "update_qty_+"))
    assert f"Количество: {quantity}" in all_text(calls)
    order_id = int(pay.rsplit("_", 1)[1])

    calls = await bot.click(BUYER, pay)
    assert "Ваш заказ создан" in all_text(to(calls, BUYER.id))
    admin = to(calls, ADMIN_CHAT_ID)
    assert f"Новый заказ #{order_id}" in all_text(admin)
    assert button(admin, "confirm_order_") == f"confirm_order_{order_id}"
    return order_id


# --- покупатель

async def test_registration_then_menu_and_restart_command(bot):
    calls = await bot.send(BUYER, "/start")
    assert "Как к вам обращаться" in all_text(calls)
    calls = await bot.send(BUYER, "Анна")
    assert "Приятно познакомиться, Анна" in all_text(calls)
    calls = await bot.send(BUYER, "Пропустить")
    text = all_text(calls)
    assert "Регистрация завершена" in text and "Медовый чат-бот" in text

    # раньше диалог застревал в ASK_PHONE и /start не работал 5 минут
    calls = await bot.send(BUYER, "/start")
    assert "Медовый чат-бот" in all_text(calls)
    assert await user_value("firstname", BUYER) == "Анна"


async def test_order_from_catalog_to_handover(bot, catalog):
    await register(BUYER)
    order_id = await place_order(bot, catalog, quantity=2)
    assert await order_status(order_id) == OrderStatus.CREATED

    # участник админ-чата подтверждает
    calls = await bot.click(ADMIN_CHAT_MEMBER, f"confirm_order_{order_id}", chat_id=ADMIN_CHAT_ID)
    assert "подтвержден" in all_text(to(calls, BUYER.id))
    assert "3 000 ₽" in all_text(to(calls, BUYER.id))
    ready = button(to(calls, ADMIN_CHAT_ID), "order_ready_")
    assert await order_status(order_id) == OrderStatus.PROCESSING

    # повторный клик по старой кнопке ничего не меняет
    calls = await bot.click(ADMIN_CHAT_MEMBER, f"confirm_order_{order_id}", chat_id=ADMIN_CHAT_ID)
    assert any("уже недоступно" in a for a in alerts(calls))

    calls = await bot.click(ADMIN_CHAT_MEMBER, ready, chat_id=ADMIN_CHAT_ID)
    pickup = button(to(calls, BUYER.id), "pickup_today_")
    assert await order_status(order_id) == OrderStatus.READY

    calls = await bot.click(BUYER, pickup)
    today = local_today().strftime("%d.%m.%Y")
    assert today in all_text(to(calls, BUYER.id))
    complete = button(to(calls, ADMIN_CHAT_ID), "order_complit_")
    assert await order_status(order_id) == OrderStatus.CUSTOMER_NOTIFIED

    calls = await bot.click(BUYER, pickup)  # второй раз — только подсказка
    assert alerts(calls) and not to(calls, ADMIN_CHAT_ID)

    calls = await bot.click(ADMIN_CHAT_MEMBER, complete, chat_id=ADMIN_CHAT_ID)
    assert "Спасибо" in all_text(to(calls, BUYER.id))
    assert await order_status(order_id) == OrderStatus.RECEIVED


async def test_seller_declines_with_reason(bot, catalog):
    await register(BUYER)
    order_id = await place_order(bot, catalog)
    calls = await bot.click(MANAGER, f"decline_order_{order_id}", chat_id=ADMIN_CHAT_ID)
    assert "причину" in all_text(calls)
    calls = await bot.send(MANAGER, "Мёд <закончился>", chat_id=ADMIN_CHAT_ID)
    customer = all_text(to(calls, BUYER.id))
    assert "отклонен" in customer and "Мёд &lt;закончился&gt;" in customer
    assert await order_status(order_id) == OrderStatus.DECLINED


async def test_new_draft_disables_old_card(bot, catalog):
    await register(BUYER)
    await bot.click(BUYER, "honey_buy")
    calls = await bot.click(BUYER, f"select_size_{catalog.product_size_id}")
    old_plus = button(calls, "update_qty_+")
    await bot.click(BUYER, f"select_size_{catalog.product_size_id}")

    calls = await bot.click(BUYER, old_plus)
    assert any("уже оформлен или недоступен" in a for a in alerts(calls))
    statuses = sorted(s for (s,) in await query("SELECT status_id FROM orders"))
    assert statuses == sorted([OrderStatus.DRAFT, OrderStatus.EXPIRED])


# --- права

async def test_stranger_cannot_use_manager_actions(bot, catalog):
    calls = await bot.send(STRANGER, "/honey_add")
    assert "Недостаточно прав" in all_text(calls)
    calls = await bot.click(STRANGER, "confirm_order_1")          # подделанная кнопка в личке
    assert any("Недостаточно прав" in a for a in alerts(calls))
    calls = await bot.send(STRANGER, "/managers")
    assert "Недостаточно прав" in all_text(calls)


async def test_owner_appoints_and_removes_manager(bot, catalog):
    await register(BUYER)
    calls = await bot.send(OWNER, f"/manager_add @{BUYER.username}")
    assert "Теперь менеджер магазина «KrasPolHoney»" in all_text(to(calls, OWNER.id))
    assert "права менеджера магазина «KrasPolHoney»" in all_text(to(calls, BUYER.id))
    assert await user_value("role_id", BUYER) == Role.MANAGER
    assert await user_value("shop_id", BUYER) == catalog.shop_id

    calls = await bot.send(BUYER, "/honey_add")                   # новый менеджер сразу получает доступ
    assert "Введите название продукта" in all_text(calls)
    await bot.send(BUYER, "/cancel")

    calls = await bot.send(OWNER, "/managers")
    calls = await bot.click(OWNER, button(calls, f"mgr_remove_{await user_value('id', BUYER)}"))
    assert await user_value("role_id", BUYER) == Role.USER
    calls = await bot.send(BUYER, "/honey_add")
    assert "Недостаточно прав" in all_text(calls)


# --- несколько магазинов

OTHER_MANAGER = STRANGER   # в этих сценариях — менеджер магазина Б


async def test_other_shop_staff_cannot_touch_order(bot, catalog):
    await register(BUYER)
    await create_second_shop(OTHER_MANAGER)
    order_id = await place_order(bot, catalog)

    # служебный чат магазина Б и его менеджер в личке — заказ витрины им не принадлежит
    calls = await bot.click(OTHER_MANAGER, f"confirm_order_{order_id}", chat_id=STAFF_CHAT_B)
    assert any("Недостаточно прав" in a for a in alerts(calls))
    calls = await bot.click(OTHER_MANAGER, f"confirm_order_{order_id}")
    assert any("Недостаточно прав" in a for a in alerts(calls))
    assert not to(calls, BUYER.id)
    assert await order_status(order_id) == OrderStatus.CREATED

    # свой служебный чат — может
    await bot.click(ADMIN_CHAT_MEMBER, f"confirm_order_{order_id}", chat_id=ADMIN_CHAT_ID)
    assert await order_status(order_id) == OrderStatus.PROCESSING


async def test_manager_sees_only_own_shop_products(bot, catalog):
    await create_second_shop(OTHER_MANAGER)
    calls = await bot.click(OTHER_MANAGER, "honey_get")
    assert "Горный мёд" not in all_text(calls) and "товаров не найдено" in all_text(calls)
    calls = await bot.click(MANAGER, "honey_get")
    assert "Горный мёд" in all_text(calls)


async def test_owner_appoints_manager_to_other_shop(bot, catalog):
    await register(BUYER)
    shop_b = await create_second_shop(OTHER_MANAGER)
    calls = await bot.send(OWNER, f"/manager_add @{BUYER.username} {SHOP_B}")
    assert "Теперь менеджер магазина «Магазин Б»" in all_text(to(calls, OWNER.id))
    assert await user_value("shop_id", BUYER) == shop_b
    calls = await bot.send(OWNER, "/manager_add @nobody_here no-such-shop")
    assert "Магазин не найден" in all_text(calls)


# --- дегустации

async def test_tasting_signup_invite_and_rsvp(bot):
    await register(BUYER)
    calls = await bot.click(BUYER, "honey_try")
    assert any("записаны на дегустацию" in a for a in alerts(calls))

    event_day = local_today() + timedelta(days=7)
    await bot.click(MANAGER, "honey_invite")
    await bot.send(MANAGER, event_day.strftime("%d.%m.%Y"))
    calls = await bot.send(MANAGER, "18:30")
    assert "Отправлено: 1" in all_text(to(calls, MANAGER.id))
    invite = to(calls, BUYER.id)
    assert "18:30" in all_text(invite) and event_day.strftime("%d.%m.%Y") in all_text(invite)

    calls = await bot.click(BUYER, button(invite, "tasting_yes_"))
    assert any("Ждём вас" in a for a in alerts(calls))
    buyer_id = await user_value("id", BUYER)
    assert await query("SELECT status FROM tasting_signups WHERE user_id = :id", id=buyer_id) == \
        [(TastingStatus.GOING.value,)]


# --- эксплуатация

async def test_conversation_survives_restart(bot, tmp_path):
    calls = await bot.send(BUYER, "/start")
    assert "Как к вам обращаться" in all_text(calls)

    await stop_bot(bot)                                  # «деплой»: процесс остановлен, состояние в файле
    restarted = await start_bot(tmp_path / "state.pickle")
    try:
        calls = await restarted.send(BUYER, "Анна")        # диалог продолжается с того же шага
        assert "Приятно познакомиться, Анна" in all_text(calls)
    finally:
        await stop_bot(restarted)
