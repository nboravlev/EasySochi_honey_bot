"""Вход в админку из браузера: одноразовая ссылка от бота → сессия в cookie.

В БД хранятся только SHA-256 хеши токенов: утечка базы не даёт войти. Ссылка живёт 10 минут
и срабатывает один раз; сессия — 14 дней, потом снова /admin в боте.
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AdminLoginToken, AdminSession
from utils.timeutils import utcnow

LOGIN_LINK_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=14)
USER_AGENT_MAX = 255


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def issue_login_token(session: AsyncSession, user_id: int) -> str:
    token = _new_token()
    session.add(AdminLoginToken(user_id=user_id, token_hash=_hash(token), expires_at=utcnow() + LOGIN_LINK_TTL))
    await session.flush()
    return token


async def redeem_login_token(session: AsyncSession, token: str, user_agent: str | None = None) -> tuple[int, str] | None:
    """Обменять ссылку на сессию. Возвращает (user_id, токен сессии) или None — ссылка неверна,
    устарела или уже использована. Погашение атомарно: двойной клик не создаст две сессии."""
    now = utcnow()
    user_id = await session.scalar(
        update(AdminLoginToken)
        .where(AdminLoginToken.token_hash == _hash(token), AdminLoginToken.used_at.is_(None),
               AdminLoginToken.expires_at > now)
        .values(used_at=now)
        .returning(AdminLoginToken.user_id)
    )
    if user_id is None:
        return None
    session_token = _new_token()
    session.add(AdminSession(
        user_id=user_id, token_hash=_hash(session_token), expires_at=now + SESSION_TTL, last_seen_at=now,
        user_agent=(user_agent or "")[:USER_AGENT_MAX] or None,
    ))
    await session.flush()
    return user_id, session_token


async def session_user_id(session: AsyncSession, token: str) -> int | None:
    now = utcnow()
    return await session.scalar(
        update(AdminSession)
        .where(AdminSession.token_hash == _hash(token), AdminSession.revoked_at.is_(None), AdminSession.expires_at > now)
        .values(last_seen_at=now)
        .returning(AdminSession.user_id)
    )


async def revoke_session(session: AsyncSession, token: str) -> None:
    await session.execute(
        update(AdminSession).where(AdminSession.token_hash == _hash(token), AdminSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke_user_sessions(session: AsyncSession, user_id: int) -> None:
    """Снятие менеджера: все его браузерные сессии перестают работать сразу."""
    await session.execute(
        update(AdminSession).where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def active_sessions(session: AsyncSession, user_id: int) -> list[AdminSession]:
    return list(await session.scalars(
        select(AdminSession)
        .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None), AdminSession.expires_at > utcnow())
        .order_by(AdminSession.id)
    ))


async def purge(session: AsyncSession) -> int:
    """Удалить истёкшие ссылки и сессии (раз в сутки, вместе с чисткой очереди уведомлений)."""
    now = utcnow()
    links = await session.execute(delete(AdminLoginToken).where(AdminLoginToken.expires_at < now - timedelta(days=1)))
    sessions = await session.execute(
        delete(AdminSession).where(or_(AdminSession.expires_at < now,
                                       AdminSession.revoked_at < now - timedelta(days=30)))
    )
    return (links.rowcount or 0) + (sessions.rowcount or 0)
