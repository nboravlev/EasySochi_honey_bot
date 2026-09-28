"""Права в Telegram-адаптере: владелец платформы, менеджер магазина, служебный чат магазина."""
from types import SimpleNamespace

import pytest
from telegram.ext import ConversationHandler

from domain.enums import Role
from services.users import StaffProfile
from utils import access

OWNER_TG = 42            # tests/conftest.py: OWNER_ID
SHOP_A, SHOP_B = 1, 2
STAFF_CHAT_A = -100500   # служебный чат магазина A
# Telegram ID → (users.id, профиль)
PEOPLE = {
    111: (11, StaffProfile(role_id=Role.MANAGER, shop_id=SHOP_A)),   # менеджер магазина A
    222: (22, StaffProfile(role_id=Role.MANAGER, shop_id=SHOP_B)),   # менеджер магазина B
    333: (33, StaffProfile(role_id=Role.USER, shop_id=None)),        # покупатель
    444: (44, StaffProfile(role_id=Role.MANAGER, shop_id=None)),     # роль без магазина — не менеджер
}


@pytest.fixture(autouse=True)
def fake_directory(monkeypatch):
    """Пользователи, роли и служебные чаты берутся из БД; в юнит-тестах — из словарей."""
    async def user_id_for_telegram(tg_id):
        return PEOPLE.get(tg_id, (None, None))[0]

    async def get_staff_profile(user_id):
        return next((p for uid, p in PEOPLE.values() if uid == user_id), None)

    async def staff_chat_shop_id(update):
        return SHOP_A if update.effective_chat.id == STAFF_CHAT_A else None

    monkeypatch.setattr(access, "user_id_for_telegram", user_id_for_telegram)
    monkeypatch.setattr(access, "get_staff_profile", get_staff_profile)
    monkeypatch.setattr(access, "staff_chat_shop_id", staff_chat_shop_id)


class FakeQuery:
    data = "x"

    def __init__(self):
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def fake_update(tg_id: int, chat_id: int):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=tg_id),
        effective_chat=SimpleNamespace(id=chat_id),
        callback_query=FakeQuery(),
    )


@access.manager_only
async def manager_handler(update, context):
    return "ok"


@access.staff_only
async def staff_handler(update, context):
    return "ok"


@access.owner_only
async def owner_handler(update, context):
    return "ok"


async def test_actor_scopes():
    owner = await access.get_actor(fake_update(OWNER_TG, OWNER_TG))
    assert owner.is_owner and owner.is_manager and owner.shop_scope is None   # все магазины
    manager_a = await access.get_actor(fake_update(111, 111))
    assert manager_a.is_manager and manager_a.shop_scope == SHOP_A and manager_a.user_id == 11
    buyer = await access.get_actor(fake_update(333, 333))
    assert not buyer.is_manager
    assert not (await access.get_actor(fake_update(444, 444))).is_manager
    stranger = await access.get_actor(fake_update(999, 999))
    assert stranger.user_id is None and not stranger.is_manager


async def test_can_manage_only_own_shop():
    assert await access.can_manage_shop(fake_update(111, 111), SHOP_A)
    assert not await access.can_manage_shop(fake_update(111, 111), SHOP_B)          # менеджер A — не B
    assert await access.can_manage_shop(fake_update(999, STAFF_CHAT_A), SHOP_A)     # служебный чат A
    assert not await access.can_manage_shop(fake_update(999, STAFF_CHAT_A), SHOP_B)  # …но не B
    assert await access.can_manage_shop(fake_update(OWNER_TG, OWNER_TG), SHOP_B)    # владелец — любой
    assert not await access.can_manage_shop(fake_update(333, 333), SHOP_A)


async def test_manager_only():
    assert await manager_handler(fake_update(111, 111), None) == "ok"
    assert await manager_handler(fake_update(OWNER_TG, OWNER_TG), None) == "ok"
    update = fake_update(999, 999)
    assert await manager_handler(update, None) == ConversationHandler.END
    assert update.callback_query.answers == [(access.DENIED_TEXT, True)]
    # участник служебного чата — не менеджер: создавать товары не может
    assert await manager_handler(fake_update(999, STAFF_CHAT_A), None) == ConversationHandler.END


async def test_staff_only():
    assert await staff_handler(fake_update(999, STAFF_CHAT_A), None) == "ok"   # служебный чат
    assert await staff_handler(fake_update(222, 222), None) == "ok"            # менеджер в личке
    assert await staff_handler(fake_update(333, 333), None) == ConversationHandler.END


async def test_owner_only():
    assert await owner_handler(fake_update(OWNER_TG, OWNER_TG), None) == "ok"
    assert await owner_handler(fake_update(111, 111), None) == ConversationHandler.END
