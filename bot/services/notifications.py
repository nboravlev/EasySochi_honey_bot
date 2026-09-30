"""Очередь исходящих уведомлений (outbox) — без привязки к платформе.

Бизнес-код ставит сообщение в очередь той же сессией, в которой меняет данные (enqueue),
и коммитит вместе. Адаптер платформы забирает строки (claim), отправляет и записывает результат
(mark_sent / mark_retry / mark_failed). Повторы — с нарастающей паузой, затем строка считается failed.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Notification, ShopChannel, UserIdentity
from domain.enums import NotificationStatus, Provider
from domain.messages import OutMessage, Recipient, ToShopStaff, ToUser
from utils.timeutils import utcnow

# служебные чаты магазина — только там, где работают кнопки продавца («Подтвердить» и т.п.): Telegram
STAFF_PROVIDERS = (Provider.TELEGRAM,)

# пауза перед повторной попыткой: после 1-й неудачи — 30 с, после 2-й — 2 мин, …
RETRY_DELAYS = (
    timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10),
    timedelta(minutes=30), timedelta(hours=1), timedelta(hours=3),
)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1     # ≈ 5 часов попыток
ERROR_MAX_LENGTH = 500

KEEP_SENT = timedelta(days=30)
KEEP_FAILED = timedelta(days=90)


def user_providers() -> tuple[Provider, ...]:
    """Платформы, куда пишем человеку (у WEB push-канала нет). VK — если настроено сообщество VK;
    новая платформа добавляется сюда вместе со своим адаптером доставки (utils/*_delivery.py)."""
    if get_settings().vk_messages_enabled:
        return (Provider.TELEGRAM, Provider.VK)
    return (Provider.TELEGRAM,)


@dataclass
class Delivery:
    """Итог немедленной отправки: отправлено / ждёт повтора / не будет доставлено."""
    sent: int = 0
    queued: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.sent > 0

    def record(self, outcome: str) -> None:
        """outcome — sent / queued / failed (результат адаптера платформы)."""
        setattr(self, outcome, getattr(self, outcome) + 1)

    def __add__(self, other: "Delivery") -> "Delivery":
        return Delivery(self.sent + other.sent, self.queued + other.queued, self.failed + other.failed)


@dataclass(frozen=True)
class Address:
    provider: str
    address: str


async def addresses(session: AsyncSession, to: Recipient) -> list[Address]:
    """Куда доставить: аккаунты человека или служебные каналы магазина в платформах с push-доставкой."""
    if isinstance(to, ToUser):
        rows = await session.execute(
            select(UserIdentity.provider, UserIdentity.external_id)
            .where(UserIdentity.user_id == to.user_id, UserIdentity.provider.in_(user_providers()))
            .order_by(UserIdentity.id)
        )
    elif isinstance(to, ToShopStaff):
        rows = await session.execute(
            select(ShopChannel.provider, ShopChannel.address)
            .where(ShopChannel.shop_id == to.shop_id, ShopChannel.purpose == "staff",
                   ShopChannel.provider.in_(STAFF_PROVIDERS))
            .order_by(ShopChannel.id)
        )
    else:
        raise TypeError(f"неизвестный получатель: {to!r}")
    return [Address(provider, address) for provider, address in rows.all()]


async def enqueue(session: AsyncSession, to: Recipient, message: OutMessage, kind: str) -> list[Notification]:
    """Поставить сообщение в очередь (без commit). Пустой список — получателю некуда доставить."""
    rows = [
        Notification(
            kind=kind, provider=a.provider, address=a.address, payload=message.to_payload(),
            user_id=to.user_id if isinstance(to, ToUser) else None,
            shop_id=to.shop_id if isinstance(to, ToShopStaff) else None,
            status=NotificationStatus.PENDING, attempts=0, next_attempt_at=utcnow(),
        )
        for a in await addresses(session, to)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def due_ids(session: AsyncSession, provider: Provider, limit: int = 50) -> list[int]:
    """Строки, которые пора (повторно) отправить, — по порядку постановки."""
    return list(await session.scalars(
        select(Notification.id)
        .where(Notification.status == NotificationStatus.PENDING, Notification.provider == provider,
               Notification.next_attempt_at <= utcnow())
        .order_by(Notification.id)
        .limit(limit)
    ))


async def claim(session: AsyncSession, notification_id: int, provider: Provider) -> Notification | None:
    """Взять строку на отправку: блокировка до конца транзакции, занятые другим процессом пропускаются.

    None — строки нет, она уже обработана, ещё не пора или она для другой платформы.
    """
    return await session.scalar(
        select(Notification)
        .where(Notification.id == notification_id, Notification.provider == provider,
               Notification.status == NotificationStatus.PENDING, Notification.next_attempt_at <= utcnow())
        .with_for_update(skip_locked=True)
    )


def mark_sent(notification: Notification, external_message_id: str | int | None = None) -> None:
    notification.status = NotificationStatus.SENT
    notification.attempts += 1
    notification.sent_at = utcnow()
    notification.last_error = None
    notification.external_message_id = str(external_message_id) if external_message_id is not None else None


def mark_failed(notification: Notification, error: str) -> None:
    """Отправить невозможно (бот заблокирован, чат не найден) — повторять бессмысленно."""
    notification.status = NotificationStatus.FAILED
    notification.attempts += 1
    notification.last_error = error[:ERROR_MAX_LENGTH]


def mark_retry(notification: Notification, error: str, delay: timedelta | None = None) -> bool:
    """Временная ошибка: повторить позже. delay — пауза, которую попросила платформа (лимиты).

    Возвращает False, если попытки исчерпаны и строка помечена failed.
    """
    notification.attempts += 1
    notification.last_error = error[:ERROR_MAX_LENGTH]
    if notification.attempts >= MAX_ATTEMPTS:
        notification.status = NotificationStatus.FAILED
        return False
    notification.next_attempt_at = utcnow() + (retry_delay(notification.attempts) if delay is None else delay)
    return True


def retry_delay(attempts: int) -> timedelta:
    return RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1]


async def purge(session: AsyncSession, now: datetime | None = None) -> int:
    """Удалить старые отправленные (30 дней) и неотправленные (90 дней) — таблица не растёт бесконечно."""
    now = now or utcnow()
    result = await session.execute(
        delete(Notification).where(
            ((Notification.status == NotificationStatus.SENT) & (Notification.created_at < now - KEEP_SENT))
            | ((Notification.status == NotificationStatus.FAILED) & (Notification.created_at < now - KEEP_FAILED))
        )
    )
    return result.rowcount or 0


async def backlog(session: AsyncSession) -> dict[str, int]:
    """Сколько строк в каком статусе — для мониторинга."""
    rows = await session.execute(select(Notification.status, func.count()).group_by(Notification.status))
    return {status: count for status, count in rows.all()}


def ids_of(rows: Iterable[Notification]) -> list[int]:
    return [row.id for row in rows]
