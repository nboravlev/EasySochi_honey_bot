from types import SimpleNamespace

from telegram.ext import ConversationHandler

from utils import access

ADMIN_CHAT_ID = -100500  # conftest


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


def test_roles():
    assert access.is_owner(42)
    assert not access.is_owner(111)
    assert access.is_manager(111) and access.is_manager(42)
    assert not access.is_manager(999)


async def test_manager_only_allows_managers_and_owner():
    assert await manager_handler(fake_update(111, 111), None) == "ok"
    assert await manager_handler(fake_update(42, 42), None) == "ok"


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
