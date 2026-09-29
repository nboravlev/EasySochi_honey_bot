"""Проверка подписи Telegram Mini App (initData).

Telegram передаёт Mini App строку initData с данными пользователя и подписью HMAC-SHA256,
ключ которой выводится из токена бота. Подделать её без токена нельзя, поэтому пароль не нужен:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode


class InvalidInitData(Exception):
    """Подпись не сходится, данные устарели или неполны."""


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    allows_write_to_pm: bool = False


def _signature(fields: dict[str, str], bot_token: str) -> str:
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int, now: float | None = None) -> TelegramUser:
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InvalidInitData("initData не разбирается") from exc
    received = fields.pop("hash", None)
    if not received or not hmac.compare_digest(received, _signature(fields, bot_token)):
        raise InvalidInitData("подпись не сходится")

    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidInitData("нет auth_date или user") from exc
    if (now if now is not None else time.time()) - auth_date > max_age_seconds:
        raise InvalidInitData("initData устарела")

    return TelegramUser(
        id=user_id,
        first_name=str(user.get("first_name") or ""),
        last_name=user.get("last_name"),
        username=user.get("username"),
        language_code=user.get("language_code"),
        allows_write_to_pm=bool(user.get("allows_write_to_pm")),
    )


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Подписанная initData — для тестов и локальной отладки фронтенда."""
    return urlencode({**fields, "hash": _signature(fields, bot_token)})
