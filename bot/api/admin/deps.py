"""Кто работает в админке и что ему можно.

Вход — один из двух:
- внутри Telegram (Mini App): заголовок «Authorization: tma <initData>», как у витрины;
- в браузере: cookie сессии после одноразовой ссылки из бота (/admin).
Права — как в боте: менеджер (users.role_id = MANAGER + shop_id) видит и меняет только свой магазин,
владелец платформы (OWNER_ID) — всё.

Защита от CSRF для cookie: изменяющие запросы должны нести заголовок X-Honey-Admin — чужой сайт
не может добавить его к запросу в браузере без разрешения CORS (а CORS у API нет).
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from api.deps import DbSession, has_platform_auth, user_from_authorization
from db.models import User
from domain.enums import Role
from services import admin_auth, users

COOKIE = "honey_admin"
COOKIE_PATH = "/api/admin"
CSRF_HEADER = "X-Honey-Admin"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Staff:
    user: User
    is_owner: bool
    shop_id: int | None          # магазин менеджера; у владельца — None
    via: str                     # telegram / session

    @property
    def scope(self) -> int | None:
        """Область видимости для services: None — все магазины."""
        return None if self.is_owner else self.shop_id

    def can_manage(self, shop_id: int) -> bool:
        return self.is_owner or self.shop_id == shop_id

    def shop_filter(self, requested: int | None) -> int | None:
        """Фильтр по магазину: владелец выбирает любой (или все), менеджер — всегда свой."""
        return requested if self.is_owner else self.shop_id


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


async def staff_of(session, user: User, via: str) -> Staff:
    is_owner = await users.is_platform_owner(session, user.id)
    if not is_owner and not (user.role_id == Role.MANAGER and user.shop_id is not None):
        raise _forbidden("Админка — только для менеджеров магазинов. Попросите владельца назначить вас.")
    return Staff(user=user, is_owner=is_owner, shop_id=None if is_owner else user.shop_id, via=via)


async def current_staff(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    session_token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
    csrf: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> Staff:
    if has_platform_auth(authorization):
        user = await user_from_authorization(session, authorization)
        return await staff_of(session, user, "telegram")

    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Войдите: отправьте боту команду /admin.")
    if request.method not in SAFE_METHODS and csrf != "1":
        raise _forbidden("Запрос без заголовка админки отклонён.")
    user_id = await admin_auth.session_user_id(session, session_token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла. Отправьте боту /admin, чтобы войти снова.")
    await session.commit()   # last_seen_at
    user = await session.get(User, user_id)
    return await staff_of(session, user, "session")


async def owner_staff(staff: Annotated[Staff, Depends(current_staff)]) -> Staff:
    if not staff.is_owner:
        raise _forbidden("Это может только владелец платформы.")
    return staff


CurrentStaff = Annotated[Staff, Depends(current_staff)]
OwnerStaff = Annotated[Staff, Depends(owner_staff)]
