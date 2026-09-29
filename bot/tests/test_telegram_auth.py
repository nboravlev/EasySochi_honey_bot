"""Подпись Telegram Mini App (initData)."""
import json
import time

import pytest

from api.telegram_auth import InvalidInitData, sign_init_data, validate_init_data

TOKEN = "123456:TEST"
DAY = 24 * 3600


def init_data(token: str = TOKEN, auth_date: float | None = None, **user) -> str:
    fields = {
        "query_id": "AAE",
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "user": json.dumps({"id": 5001, "first_name": "Анна", "username": "anna", "allows_write_to_pm": True, **user},
                           ensure_ascii=False),
    }
    return sign_init_data(fields, token)


def test_valid_init_data():
    user = validate_init_data(init_data(), TOKEN, DAY)
    assert (user.id, user.first_name, user.username, user.allows_write_to_pm) == (5001, "Анна", "anna", True)


def test_signed_with_other_token_is_rejected():
    with pytest.raises(InvalidInitData):
        validate_init_data(init_data(token="999:OTHER"), TOKEN, DAY)


def test_tampered_user_is_rejected():
    forged = init_data().replace("5001", "5002")
    with pytest.raises(InvalidInitData):
        validate_init_data(forged, TOKEN, DAY)


def test_expired_init_data_is_rejected():
    old = init_data(auth_date=time.time() - 2 * DAY)
    with pytest.raises(InvalidInitData):
        validate_init_data(old, TOKEN, DAY)
    assert validate_init_data(old, TOKEN, 3 * DAY).id == 5001


@pytest.mark.parametrize("raw", ["", "garbage", "hash=abc", "user=%7B%7D&auth_date=1"])
def test_malformed_init_data_is_rejected(raw):
    with pytest.raises(InvalidInitData):
        validate_init_data(raw, TOKEN, DAY)
