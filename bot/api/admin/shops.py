"""Магазины, точки выдачи, служебные чаты и менеджеры. Менять — владелец платформы; менеджер видит свой магазин."""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from api.admin.deps import CurrentStaff, OwnerStaff
from api.admin.schemas import (
    AdminLocationIn,
    AdminLocationOut,
    AdminShopOut,
    ManagerIn,
    ManagerOut,
    ShopCreate,
    ShopUpdate,
    StaffChatIn,
)
from api.deps import DbSession, Notifications
from api.schemas import ShopRef
from db.models import Shop, ShopLocation, User
from domain.enums import Provider, Role
from domain.messages import OutMessage, ToUser
from services import admin_auth, notifications, shops, users
from services.shops import ShopError
from utils.escape import safe_html
from utils.logging_config import structured_logger

router = APIRouter(tags=["админка: магазины"])


async def shop_out(session, shop: Shop, storefront_id: int | None, managers: dict[int, int]) -> AdminShopOut:
    staff_chat = next((c.address for c in shop.channels if c.provider == Provider.TELEGRAM and c.purpose == "staff"), None)
    return AdminShopOut(
        id=shop.id, slug=shop.slug, name=shop.name, phone=shop.contact_phone, is_active=shop.is_active,
        is_storefront=shop.id == storefront_id, staff_chat_id=staff_chat,
        locations=[
            AdminLocationOut(
                id=loc.id, name=loc.name, address=loc.address, opening_hours=loc.opening_hours,
                latitude=point.latitude if point else None, longitude=point.longitude if point else None,
                is_pickup=loc.is_pickup, is_active=loc.is_active,
            )
            for loc, point in await shops.all_locations(session, shop.id)
        ],
        managers=managers.get(shop.id, 0),
    )


async def _shop_response(session, shop_id: int) -> AdminShopOut:
    [shop] = await shops.list_shops(session, shop_id)
    return await shop_out(session, shop, await shops.storefront_shop_id(session), await _manager_counts(session))


async def _manager_counts(session) -> dict[int, int]:
    rows = await session.execute(
        select(User.shop_id, func.count()).where(User.role_id == Role.MANAGER).group_by(User.shop_id)
    )
    return dict(rows.all())


async def _shop(session, shop_id: int) -> Shop:
    shop = await shops.get_shop(session, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Магазин не найден.")
    return shop


@router.get("/shops", response_model=list[AdminShopOut])
async def list_shops(staff: CurrentStaff, session: DbSession) -> list[AdminShopOut]:
    storefront_id, counts = await shops.storefront_shop_id(session), await _manager_counts(session)
    return [await shop_out(session, s, storefront_id, counts) for s in await shops.list_shops(session, staff.scope)]


@router.post("/shops", response_model=AdminShopOut, status_code=status.HTTP_201_CREATED)
async def create_shop(body: ShopCreate, staff: OwnerStaff, session: DbSession) -> AdminShopOut:
    try:
        shop = await shops.create_shop(session, body.slug, body.name, body.phone)
    except ShopError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    structured_logger.info("Shop created", user_id=staff.user.id, action="admin_shop_created",
                           context={"shop_id": shop.id, "slug": shop.slug})
    return await _shop_response(session, shop.id)


@router.patch("/shops/{shop_id}", response_model=AdminShopOut)
async def update_shop(shop_id: int, body: ShopUpdate, staff: OwnerStaff, session: DbSession) -> AdminShopOut:
    shop = await _shop(session, shop_id)
    if body.name is not None:
        shop.name = body.name.strip()
    if body.phone is not None:
        shop.contact_phone = body.phone.strip() or None
    if body.is_active is not None:
        shop.is_active = body.is_active
    await session.commit()
    return await _shop_response(session, shop_id)


@router.put("/shops/{shop_id}/staff-chat", response_model=AdminShopOut)
async def set_staff_chat(shop_id: int, body: StaffChatIn, staff: OwnerStaff, session: DbSession) -> AdminShopOut:
    """Служебный Telegram-чат магазина: туда приходят новые заказы с кнопками. Бот должен быть в группе."""
    await _shop(session, shop_id)
    if body.telegram_chat_id is None:
        await shops.remove_staff_channel(session, shop_id, Provider.TELEGRAM)
    else:
        await shops.set_staff_channel(session, shop_id, Provider.TELEGRAM, body.telegram_chat_id)
    await session.commit()
    return await _shop_response(session, shop_id)


@router.post("/shops/{shop_id}/locations", response_model=AdminShopOut, status_code=status.HTTP_201_CREATED)
async def add_location(shop_id: int, body: AdminLocationIn, staff: OwnerStaff, session: DbSession) -> AdminShopOut:
    await _shop(session, shop_id)
    await shops.save_location(session, shop_id, None, **body.model_dump())
    await session.commit()
    return await _shop_response(session, shop_id)


@router.put("/locations/{location_id}", response_model=AdminShopOut)
async def update_location(location_id: int, body: AdminLocationIn, staff: OwnerStaff, session: DbSession) -> AdminShopOut:
    location = await session.get(ShopLocation, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Точка не найдена.")
    await shops.save_location(session, location.shop_id, location, **body.model_dump())
    await session.commit()
    return await _shop_response(session, location.shop_id)


# --- менеджеры


def manager_out(user: User, owner_id: int | None) -> ManagerOut:
    telegram = next((i for i in user.identities if i.provider == Provider.TELEGRAM), None)
    return ManagerOut(
        user_id=user.id, name=user.firstname, telegram_id=telegram.external_id if telegram else None,
        username=(telegram.username if telegram else None) or user.username,
        shop=ShopRef(id=user.shop.id, name=user.shop.name) if user.shop else None,
        is_owner=user.id == owner_id,
    )


@router.get("/managers", response_model=list[ManagerOut])
async def list_managers(staff: OwnerStaff, session: DbSession) -> list[ManagerOut]:
    return [manager_out(u, staff.user.id) for u in await users.list_managers(session)]


@router.post("/managers", response_model=ManagerOut, status_code=status.HTTP_201_CREATED)
async def add_manager(body: ManagerIn, staff: OwnerStaff, session: DbSession, notifier: Notifications) -> ManagerOut:
    """Назначить менеджером магазина — как /manager_add в боте. Человек должен хотя бы раз нажать /start."""
    shop = await _shop(session, body.shop_id)
    user = await users.find_user(session, body.user)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=f"Пользователь {body.user} не найден. Попросите его сначала нажать /start в боте.")
    await users.set_manager(session, user, shop.id)
    pending = await notifications.enqueue_all(session, [(ToUser(user.id), OutMessage(
        f"🐝 Вам выданы права менеджера магазина «{safe_html(shop.name)}». Нажмите /start, чтобы открыть меню."
    ), "manager_added")])
    await session.commit()
    await notifier.deliver(pending)
    structured_logger.info("Manager added in admin", user_id=staff.user.id, action="manager_added",
                           context={"manager_id": user.id, "shop_id": shop.id})
    [manager] = [m for m in await users.list_managers(session) if m.id == user.id]
    return manager_out(manager, staff.user.id)


@router.delete("/managers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_manager(user_id: int, staff: OwnerStaff, session: DbSession, notifier: Notifications) -> None:
    if user_id == staff.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Владельца снять нельзя — он задаётся OWNER_ID в .env.")
    user = await session.get(User, user_id)
    if user is None or user.role_id != Role.MANAGER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Менеджер не найден.")
    await users.set_manager(session, user, None)
    await admin_auth.revoke_user_sessions(session, user_id)   # выход из админки сразу
    pending = await notifications.enqueue_all(
        session, [(ToUser(user_id), OutMessage("Права менеджера медового бота сняты."), "manager_removed")]
    )
    await session.commit()
    await notifier.deliver(pending)
    structured_logger.info("Manager removed in admin", user_id=staff.user.id, action="manager_removed",
                           context={"manager_id": user_id})
