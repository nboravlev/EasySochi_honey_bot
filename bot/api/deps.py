"""Зависимости FastAPI: сессия БД, текущий пользователь (по подписи Telegram), шлюз в Telegram."""
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.telegram_auth import InvalidInitData, validate_init_data
from api.telegram_gateway import TelegramGateway
from config import get_settings
from db.db_async import get_async_session
from db.models import User
from domain.enums import Provider
from services import identity
from utils.logging_config import bind_update_context

NAME_MAX_LENGTH = 50   # users.firstname


async def db() -> AsyncIterator[AsyncSession]:
    async with get_async_session() as session:
        yield session


def gateway(request: Request) -> TelegramGateway:
    return request.app.state.telegram


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "tma"})


async def current_user(
    session: Annotated[AsyncSession, Depends(db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Покупатель из заголовка «Authorization: tma <initData>» (Telegram Mini App).

    Пользователь создаётся при первом входе — так же, как при /start в боте. Позже здесь же
    появится «vk <параметры запуска>» для VK Mini App.
    """
    scheme, _, payload = (authorization or "").partition(" ")
    if scheme.lower() != "tma" or not payload:
        raise _unauthorized("Откройте витрину в Telegram, чтобы оформить заказ.")
    settings = get_settings()
    try:
        tg = validate_init_data(payload, settings.bot_token, settings.webapp_auth_max_age_hours * 3600)
    except InvalidInitData as exc:
        raise _unauthorized(f"Не удалось проверить вход через Telegram: {exc}. Перезапустите витрину.") from exc

    user, created = await identity.get_or_create_user(session, Provider.TELEGRAM, tg.id, username=tg.username)
    if created or not user.firstname:
        user.firstname = tg.first_name[:NAME_MAX_LENGTH] or None
        if tg.username and not user.username:
            user.username = tg.username[:NAME_MAX_LENGTH]
        await session.commit()
    bind_update_context(user_id=user.id, telegram_id=tg.id)
    return user


# типы параметров маршрутов: `user: CurrentUser`, `session: DbSession`, `telegram: Telegram`
DbSession = Annotated[AsyncSession, Depends(db)]
CurrentUser = Annotated[User, Depends(current_user)]
Telegram = Annotated[TelegramGateway, Depends(gateway)]
