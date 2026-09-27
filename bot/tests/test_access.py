from types import SimpleNamespace

import pytest
from telegram.ext import ConversationHandler

from domain.enums import Role
from utils import access

ADMIN_CHAT_ID = -100500  # conftest
OWNER_ID = 42            # conftest
ROLES = {111: Role.MANAGER, 222: Role.USER}


@pytest.fixture(autouse=True)
def roles_from_memory(monkeypatch):
    """Роль берётся из БД; в юнит-тестах подменяем её словарём."""
    async def fake_get_role(tg_user_id):
        return ROLES.get(tg_user_id)
    monkeypatch.setattr(access, "get_role", fake_get_role)


class FakeQuery:
    data = "x"

    def __init__(self):
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def fake_update(user_id: int, chat_id: int):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        callback_query=FakeQuery(),
        effective_message=None,
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


async def test_roles():
    assert access.is_owner(OWNER_ID)
    assert not access.is_owner(111)
    assert await access.is_manager(111)
    assert await access.is_manager(OWNER_ID)       # владелец — всегда менеджер, даже без строки в БД
    assert not await access.is_manager(222)        # роль USER
    assert not await access.is_manager(999)        # нет в БД
    assert not await access.is_manager(None)


async def test_manager_only_allows_managers_and_owner():
    assert await manager_handler(fake_update(111, 111), None) == "ok"
    assert await manager_handler(fake_update(OWNER_ID, OWNER_ID), None) == "ok"


async def test_manager_only_denies_stranger_with_alert():
    update = fake_update(999, 999)
    assert await manager_handler(update, None) == ConversationHandler.END
    assert update.callback_query.answers == [(access.DENIED_TEXT, True)]


async def test_manager_only_denies_stranger_even_in_admin_chat():
    assert await manager_handler(fake_update(999, ADMIN_CHAT_ID), None) == ConversationHandler.END


async def test_staff_only():
    assert await staff_handler(fake_update(999, ADMIN_CHAT_ID), None) == "ok"   # участник админ-чата
    assert await staff_handler(fake_update(111, 111), None) == "ok"             # менеджер в личке
    assert await staff_handler(fake_update(999, 999), None) == ConversationHandler.END


async def test_owner_only():
    assert await owner_handler(fake_update(OWNER_ID, OWNER_ID), None) == "ok"
    assert await owner_handler(fake_update(111, 111), None) == ConversationHandler.END  # менеджер — не владелец
