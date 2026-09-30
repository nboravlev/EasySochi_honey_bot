"""Вход в админку из браузера (ссылка от бота → cookie), выход, «кто я»."""
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from api.admin.deps import COOKIE, COOKIE_PATH, CurrentStaff, Staff, staff_of
from api.admin.schemas import AdminMe, LoginIn
from api.deps import DbSession
from api.schemas import ShopRef
from db.models import User
from services import admin_auth, shops
from utils.logging_config import structured_logger

router = APIRouter(tags=["админка: вход"])


async def me_out(session, staff: Staff) -> AdminMe:
    shop = await shops.get_shop(session, staff.shop_id) if staff.shop_id else None
    return AdminMe(
        user_id=staff.user.id, name=staff.user.firstname or staff.user.username, is_owner=staff.is_owner,
        shop=ShopRef(id=shop.id, name=shop.name) if shop else None, via=staff.via,
    )


@router.post("/login", response_model=AdminMe)
async def login(body: LoginIn, request: Request, response: Response, session: DbSession) -> AdminMe:
    """Обменять одноразовую ссылку из бота на сессию (cookie HttpOnly, только для /api/admin)."""
    redeemed = await admin_auth.redeem_login_token(session, body.token, request.headers.get("user-agent"))
    if redeemed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="Ссылка недействительна или уже использована. Отправьте боту /admin ещё раз.")
    user_id, session_token = redeemed
    staff = await staff_of(session, await session.get(User, user_id), "session")   # 403, если уже не менеджер
    await session.commit()
    response.set_cookie(
        COOKIE, session_token, max_age=int(admin_auth.SESSION_TTL.total_seconds()), path=COOKIE_PATH,
        httponly=True, secure=True, samesite="strict",
    )
    structured_logger.info("Admin login", user_id=user_id, action="admin_login", context={"owner": staff.is_owner})
    return await me_out(session, staff)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, session: DbSession, session_token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> None:
    if session_token:
        await admin_auth.revoke_session(session, session_token)
        await session.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


@router.get("/me", response_model=AdminMe)
async def me(staff: CurrentStaff, session: DbSession) -> AdminMe:
    return await me_out(session, staff)
