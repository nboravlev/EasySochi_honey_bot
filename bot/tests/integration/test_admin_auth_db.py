"""Вход в админку на PostgreSQL: одноразовые ссылки, сессии, отзыв, чистка."""
from datetime import timedelta

from sqlalchemy import select, update

from db.models import AdminLoginToken, AdminSession
from services import admin_auth
from utils.timeutils import utcnow


async def test_link_is_single_use_and_stored_hashed(session, world):
    token = await admin_auth.issue_login_token(session, world.seller.id)
    stored = await session.scalar(select(AdminLoginToken.token_hash).where(AdminLoginToken.user_id == world.seller.id))
    assert token not in stored and len(stored) == 64

    user_id, session_token = await admin_auth.redeem_login_token(session, token, "Firefox")
    assert user_id == world.seller.id
    assert await admin_auth.redeem_login_token(session, token) is None          # второй раз — нет
    assert await admin_auth.session_user_id(session, session_token) == world.seller.id
    assert await admin_auth.session_user_id(session, "forged") is None


async def test_expired_link(session, world):
    token = await admin_auth.issue_login_token(session, world.seller.id)
    await session.execute(update(AdminLoginToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    assert await admin_auth.redeem_login_token(session, token) is None


async def test_logout_and_revoke_all(session, world):
    _, first = await admin_auth.redeem_login_token(session, await admin_auth.issue_login_token(session, world.seller.id))
    _, second = await admin_auth.redeem_login_token(session, await admin_auth.issue_login_token(session, world.seller.id))
    await admin_auth.revoke_session(session, first)
    assert await admin_auth.session_user_id(session, first) is None
    assert await admin_auth.session_user_id(session, second) == world.seller.id
    await admin_auth.revoke_user_sessions(session, world.seller.id)
    assert await admin_auth.session_user_id(session, second) is None


async def test_expired_session_and_purge(session, world):
    _, token = await admin_auth.redeem_login_token(session, await admin_auth.issue_login_token(session, world.seller.id))
    await session.execute(update(AdminSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    assert await admin_auth.session_user_id(session, token) is None
    assert await admin_auth.purge(session) >= 1
    assert await session.scalar(select(AdminSession.id).where(AdminSession.user_id == world.seller.id)) is None
