import pytest
from sqlalchemy.engine import make_url

from config import DatabaseSettings, Settings


def make_settings(**env) -> Settings:
    base = {"bot_token": "t", "admin_chat_id": -1, "owner_id": None}
    return Settings(_env_file=None, **{**base, **env})


@pytest.mark.parametrize("raw", ["111,222", "[111, 222]", " 111 , 222 ,", "111,,222"])
def test_manager_list_formats(raw):
    assert make_settings(manager_list=raw).manager_ids == {111, 222}


def test_owner_is_manager():
    assert make_settings(manager_list="111", owner_id=42).manager_ids == {111, 42}


def test_empty_owner_env_is_none(monkeypatch):
    monkeypatch.setenv("OWNER_ID", "")
    assert Settings(_env_file=None).owner_id is None


def test_database_url_escapes_password_and_uses_internal_port():
    db = DatabaseSettings(_env_file=None, postgres_user="u", postgres_password="p@ss%w/rd", postgres_db="d", db_host="h")
    url = make_url(db.database_url)
    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss%w/rd"
    assert (url.host, url.port, url.database) == ("h", 5432, "d")


def test_postgres_port_is_host_port_and_ignored(monkeypatch):
    # POSTGRES_PORT в .env — порт на хосте (5335); внутри сети бот ходит на 5432
    monkeypatch.setenv("POSTGRES_PORT", "5335")
    db = DatabaseSettings(_env_file=None, postgres_user="u", postgres_password="p", postgres_db="d")
    assert make_url(db.database_url).port == 5432
