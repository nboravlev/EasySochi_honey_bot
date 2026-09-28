"""Очередь уведомлений на PostgreSQL: адресация, выборка к отправке, чистка."""
from datetime import timedelta

from db.models import Notification, UserIdentity
from domain.enums import NotificationStatus, Provider
from domain.messages import Button, OutMessage, ToShopStaff, ToUser
from services import identity, notifications, shops
from utils.timeutils import utcnow

from .conftest import BUYER_TG

MESSAGE = OutMessage("Привет", [[Button("Ок", action="ok")]])
STAFF_CHAT = -100777


async def test_enqueue_resolves_addresses(session, world):
    rows = await notifications.enqueue(session, ToUser(world.buyer.id), MESSAGE, "test")
    assert [(r.provider, r.address, r.user_id) for r in rows] == [(Provider.TELEGRAM, str(BUYER_TG), world.buyer.id)]
    assert rows[0].payload == MESSAGE.to_payload() and rows[0].status == NotificationStatus.PENDING

    # у магазина Б нет служебного чата — доставлять некуда
    assert await notifications.enqueue(session, ToShopStaff(world.shop_b.id), MESSAGE, "test") == []
    await shops.set_staff_channel(session, world.shop_a.id, Provider.TELEGRAM, STAFF_CHAT)
    staff = await notifications.enqueue(session, ToShopStaff(world.shop_a.id), MESSAGE, "test")
    assert [(r.address, r.shop_id) for r in staff] == [(str(STAFF_CHAT), world.shop_a.id)]


async def test_enqueue_skips_platforms_without_push(session, world):
    # пользователь сайта: push-канала нет — уведомлять некуда
    web_user, _ = await identity.get_or_create_user(session, Provider.WEB, "web-only")
    assert await notifications.enqueue(session, ToUser(web_user.id), MESSAGE, "test") == []

    # у человека Telegram и сайт — уходит только в Telegram
    session.add(UserIdentity(user_id=world.buyer.id, provider=Provider.WEB, external_id="web-buyer"))
    await session.flush()
    rows = await notifications.enqueue(session, ToUser(world.buyer.id), MESSAGE, "test")
    assert [r.provider for r in rows] == [Provider.TELEGRAM]


async def test_due_and_claim(session, world):
    first, second, later, done = [
        (await notifications.enqueue(session, ToUser(world.buyer.id), MESSAGE, f"n{i}"))[0] for i in range(4)
    ]
    later.next_attempt_at = utcnow() + timedelta(minutes=5)
    notifications.mark_sent(done, 1)
    await session.flush()

    due = await notifications.due_ids(session, Provider.TELEGRAM)
    mine = [i for i in due if i in {first.id, second.id, later.id, done.id}]
    assert mine == [first.id, second.id]                      # по порядку, без отложенных и отправленных
    assert await notifications.due_ids(session, Provider.VK) == []

    assert (await notifications.claim(session, first.id, Provider.TELEGRAM)) is first
    assert await notifications.claim(session, first.id, Provider.VK) is None
    assert await notifications.claim(session, later.id, Provider.TELEGRAM) is None
    assert await notifications.claim(session, done.id, Provider.TELEGRAM) is None


async def test_purge_old_rows(session, world):
    rows = [(await notifications.enqueue(session, ToUser(world.buyer.id), MESSAGE, f"p{i}"))[0] for i in range(4)]
    old_sent, fresh_sent, old_failed, old_pending = rows
    for row in (old_sent, fresh_sent):
        notifications.mark_sent(row)
    notifications.mark_failed(old_failed, "blocked")
    long_ago = utcnow() - timedelta(days=100)
    for row in (old_sent, old_failed, old_pending):
        row.created_at = long_ago
    await session.flush()

    assert await notifications.purge(session) >= 2
    left = {r.id for r in (await session.execute(
        Notification.__table__.select().where(Notification.id.in_([r.id for r in rows]))
    )).all()}
    # старые отправленные и неотправленные удалены; свежие и ждущие отправки — остаются
    assert left == {fresh_sent.id, old_pending.id}
    assert (await notifications.backlog(session)).get(NotificationStatus.PENDING, 0) >= 1
