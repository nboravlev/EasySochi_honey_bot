"""Статистика продаж (за период) и очередь уведомлений (владелец: что не дошло, отправить повторно)."""
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from api.admin.deps import CurrentStaff, OwnerStaff
from api.admin.schemas import BucketOut, DeliveryOut, NotificationOut, ProductSalesOut, StatsOut, TastingOut
from api.deps import DbSession, Notifications
from db.models import Notification
from domain.enums import NotificationStatus
from domain.messages import OutMessage
from services import stats
from utils.timeutils import utcnow
from utils.vk_delivery import to_plain_text

router = APIRouter(tags=["админка: статистика"])

PERIODS = {7, 30, 90, 365}


def _bucket(bucket: stats.Bucket) -> BucketOut:
    return BucketOut(count=bucket.count, total=bucket.total)


@router.get("/stats", response_model=StatsOut)
async def get_stats(
    staff: CurrentStaff, session: DbSession, shop_id: int | None = None, days: int | None = None,
) -> StatsOut:
    """Продажи по товарам и заказы по статусам; days — за последние N дней (7/30/90/365), без него — за всё время."""
    if days is not None and days not in PERIODS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Период: 7, 30, 90 или 365 дней.")
    since = utcnow() - timedelta(days=days) if days else None
    result = await stats.collect(session, staff.shop_filter(shop_id), since=since)
    nxt = result.next_tasting
    return StatsOut(
        period_days=days,
        sales=[ProductSalesOut(name=name, kg=kg, total=total) for name, kg, total in result.sales_by_product],
        new=_bucket(result.new), in_progress=_bucket(result.in_progress),
        completed=_bucket(result.completed), declined=_bucket(result.declined),
        customers=result.active_users, tasting_waiting=result.tasting_waiting,
        next_tasting=TastingOut(starts_at=nxt.event.starts_at, invited=nxt.invited, going=nxt.going,
                                declined=nxt.declined) if nxt else None,
    )


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id, kind=row.kind, provider=row.provider, status=row.status, attempts=row.attempts,
        last_error=row.last_error, created_at=row.created_at, next_attempt_at=row.next_attempt_at,
        user_id=row.user_id, shop_id=row.shop_id,
        text=to_plain_text(OutMessage.from_payload(row.payload).text)[:300],
    )


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    staff: OwnerStaff, session: DbSession,
    status_filter: Annotated[Literal["failed", "pending"], Query(alias="status")] = "failed",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[NotificationOut]:
    """Недоставленные (failed) или ждущие повтора (pending) уведомления, новые сверху."""
    rows = await session.scalars(
        select(Notification).where(Notification.status == status_filter)
        .order_by(Notification.id.desc()).limit(limit)
    )
    return [notification_out(r) for r in rows]


@router.post("/notifications/{notification_id}/retry", response_model=DeliveryOut)
async def retry_notification(
    notification_id: int, staff: OwnerStaff, session: DbSession, notifier: Notifications,
) -> DeliveryOut:
    """Отправить ещё раз (например, покупатель разблокировал бота или бота добавили в группу)."""
    row = await session.get(Notification, notification_id)
    if row is None or row.status == NotificationStatus.SENT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Уведомление не найдено или уже отправлено.")
    row.status, row.attempts, row.next_attempt_at = NotificationStatus.PENDING, 0, utcnow()
    await session.commit()
    delivery = await notifier.deliver([notification_id])
    return DeliveryOut(sent=delivery.sent, queued=delivery.queued, failed=delivery.failed)
