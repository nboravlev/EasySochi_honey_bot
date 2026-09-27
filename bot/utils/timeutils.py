"""Время: в БД — timestamptz (UTC), пользователю — по Москве (там пасека)."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Europe/Moscow")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime) -> datetime:
    """UTC (или naive-UTC из старых данных) → время пасеки."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BUSINESS_TZ)


def local_today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def format_local(dt: datetime | None, fmt: str = "%H:%M %d.%m.%Y") -> str:
    return to_local(dt).strftime(fmt) if dt else "—"
