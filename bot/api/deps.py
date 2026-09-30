"""Зависимости FastAPI: сессия БД, текущий пользователь (по подписи платформы), доставка уведомлений."""
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.notifier import Notifier
from api.telegram_auth import InvalidInitData, validate_init_data
from api.vk_auth import InvalidLaunchParams, validate_launch_params
from config import get_settings
from db.db_async import get_async_session
from db.models import User
from domain.enums import Provider
from services import identity
from utils.logging_config import bind_update_context

NAME_MAX_LENGTH = 50   # users.firstname
LOGIN_HINT = "Откройте витрину в Telegram или ВКонтакте, чтобы оформить заказ."


async def db() -> AsyncIterator[AsyncSession]:
    async with get_async_session() as session:
        yield session


def notifier(request: Request) -> Notifier:
    return request.app.state.notifier


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "tma, vk"})


async def _telegram_user(session: AsyncSession, init_data: str) -> User:
    settings = get_settings()
    try:
        tg = validate_init_data(init_data, settings.bot_token, settings.webapp_auth_max_age_hours * 3600)
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


async def _vk_user(session: AsyncSession, launch_params: str) -> User:
    settings = get_settings()
    if not settings.vk_auth_enabled:
        raise _unauthorized("Вход через ВКонтакте не настроен.")
    try:
        vk = validate_launch_params(
            launch_params, settings.vk_app_secret, settings.vk_app_id, settings.webapp_auth_max_age_hours * 3600
        )
    except InvalidLaunchParams as exc:
        raise _unauthorized(f"Не удалось проверить вход через ВКонтакте: {exc}. Перезапустите витрину.") from exc

    # имени в параметрах запуска нет — его присылает витрина (PATCH /api/me из VKWebAppGetUserInfo)
    user, created = await identity.get_or_create_user(session, Provider.VK, vk.id)
    if created:
        await session.commit()
    bind_update_context(user_id=user.id, vk_id=vk.id)
    return user


async def current_user(
    session: Annotated[AsyncSession, Depends(db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Покупатель по заголовку Authorization с подписанными платформой данными:

    - «tma <initData>» — Telegram Mini App;
    - «vk <параметры запуска>» — VK Mini App.

    Пользователь создаётся при первом входе — так же, как при /start в боте.
    """
    scheme, _, payload = (authorization or "").partition(" ")
    scheme = scheme.lower()
    if not payload or scheme not in ("tma", "vk"):
        raise _unauthorized(LOGIN_HINT)
    return await (_telegram_user if scheme == "tma" else _vk_user)(session, payload)


# типы параметров маршрутов: `user: CurrentUser`, `session: DbSession`, `notifications: Notifications`
DbSession = Annotated[AsyncSession, Depends(db)]
CurrentUser = Annotated[User, Depends(current_user)]
Notifications = Annotated[Notifier, Depends(notifier)]
