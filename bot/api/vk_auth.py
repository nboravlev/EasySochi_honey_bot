"""Проверка подписи параметров запуска VK Mini App.

VK открывает Mini App по адресу с параметрами vk_user_id, vk_app_id, vk_ts, … и подписью sign —
HMAC-SHA256 от отсортированных vk_*-параметров на «Защищённом ключе» приложения (base64url без «=»).
Без ключа подпись не подделать: https://dev.vk.com/ru/mini-apps/development/launch-params-sign
"""
import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode


class InvalidLaunchParams(Exception):
    """Подпись не сходится, приложение чужое или параметры устарели."""


@dataclass(frozen=True)
class VkUser:
    id: int
    notifications_enabled: bool = False
    platform: str | None = None


def _signature(vk_params: dict[str, str], secret: str) -> str:
    payload = urlencode(sorted(vk_params.items()), doseq=True)
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def validate_launch_params(
    query: str, secret: str, app_id: int, max_age_seconds: int, now: float | None = None
) -> VkUser:
    """query — строка параметров запуска (location.search без «?»)."""
    try:
        params = dict(parse_qsl(query.lstrip("?"), keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InvalidLaunchParams("параметры запуска не разбираются") from exc
    received = params.get("sign")
    vk_params = {k: v for k, v in params.items() if k.startswith("vk_")}
    if not received or not hmac.compare_digest(received, _signature(vk_params, secret)):
        raise InvalidLaunchParams("подпись не сходится")

    try:
        user_id = int(vk_params["vk_user_id"])
        launched_at = int(vk_params["vk_ts"])
        launched_app = int(vk_params["vk_app_id"])
    except (KeyError, ValueError) as exc:
        raise InvalidLaunchParams("нет vk_user_id, vk_ts или vk_app_id") from exc
    if launched_app != app_id:
        raise InvalidLaunchParams("параметры другого приложения")
    if (now if now is not None else time.time()) - launched_at > max_age_seconds:
        raise InvalidLaunchParams("параметры запуска устарели")

    return VkUser(
        id=user_id,
        notifications_enabled=vk_params.get("vk_are_notifications_enabled") == "1",
        platform=vk_params.get("vk_platform"),
    )


def sign_launch_params(vk_params: dict[str, str], secret: str) -> str:
    """Подписанные параметры запуска — для тестов и локальной отладки фронтенда."""
    return urlencode({**vk_params, "sign": _signature(vk_params, secret)})
