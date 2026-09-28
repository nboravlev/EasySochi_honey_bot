"""Дегустации: лист ожидания → приглашение на мероприятие → ответ «Приду» / «Не смогу»."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import TastingEvent, TastingSignup
from domain.enums import TastingStatus
from utils.timeutils import utcnow

# на приглашение можно ответить и передумать до начала мероприятия
ANSWERABLE = (TastingStatus.INVITED, TastingStatus.GOING, TastingStatus.DECLINED)


@dataclass(frozen=True)
class EventSummary:
    event: TastingEvent
    invited: int
    going: int
    declined: int


async def signup(session: AsyncSession, shop_id: int, user_id: int) -> tuple[TastingSignup, bool]:
    """Запись в лист ожидания магазина. Возвращает (запись, создана_сейчас)."""
    existing = await session.scalar(
        select(TastingSignup).where(
            TastingSignup.shop_id == shop_id,
            TastingSignup.user_id == user_id,
            TastingSignup.status == TastingStatus.WAITING,
        )
    )
    if existing:
        return existing, False
    record = TastingSignup(shop_id=shop_id, user_id=user_id, status=TastingStatus.WAITING)
    session.add(record)
    await session.flush()
    return record, True


async def invite_waiting(
    session: AsyncSession, shop_id: int, starts_at: datetime, created_by: int | None
) -> tuple[TastingEvent, list[TastingSignup]]:
    """Создаёт мероприятие магазина и переводит его лист ожидания в «приглашён»."""
    event = TastingEvent(shop_id=shop_id, starts_at=starts_at, created_by=created_by)
    session.add(event)
    await session.flush()
    waiting = list(
        (await session.scalars(select(TastingSignup).where(
            TastingSignup.shop_id == shop_id, TastingSignup.status == TastingStatus.WAITING
        ))).all()
    )
    for record in waiting:
        record.event_id = event.id
        record.status = TastingStatus.INVITED
    await session.flush()
    return event, waiting


async def respond(session: AsyncSession, signup_id: int, user_id: int, going: bool) -> TastingSignup | None:
    """Ответ на приглашение. None — если приглашение чужое, не существует или мероприятие уже прошло."""
    record = await session.scalar(
        select(TastingSignup).options(selectinload(TastingSignup.event)).where(TastingSignup.id == signup_id)
    )
    if (record is None or record.user_id != user_id or record.status not in ANSWERABLE
            or record.event is None or record.event.starts_at < utcnow()):
        return None
    record.status = TastingStatus.GOING if going else TastingStatus.DECLINED
    await session.flush()
    return record


async def waiting_count(session: AsyncSession, shop_id: int | None) -> int:
    """shop_id=None — по всем магазинам."""
    stmt = select(func.count()).select_from(TastingSignup).where(TastingSignup.status == TastingStatus.WAITING)
    if shop_id is not None:
        stmt = stmt.where(TastingSignup.shop_id == shop_id)
    return await session.scalar(stmt) or 0


async def next_event_summary(session: AsyncSession, shop_id: int | None) -> EventSummary | None:
    """Ближайшая дегустация магазина (shop_id=None — ближайшая среди всех)."""
    stmt = select(TastingEvent).where(TastingEvent.starts_at >= utcnow()).order_by(TastingEvent.starts_at).limit(1)
    if shop_id is not None:
        stmt = stmt.where(TastingEvent.shop_id == shop_id)
    event = await session.scalar(stmt)
    if event is None:
        return None
    rows = dict(
        (await session.execute(
            select(TastingSignup.status, func.count())
            .where(TastingSignup.event_id == event.id)
            .group_by(TastingSignup.status)
        )).all()
    )
    return EventSummary(
        event=event,
        invited=sum(rows.values()),
        going=rows.get(TastingStatus.GOING, 0),
        declined=rows.get(TastingStatus.DECLINED, 0),
    )
