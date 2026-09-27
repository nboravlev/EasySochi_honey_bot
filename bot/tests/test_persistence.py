"""Выбор хранилища состояния диалогов при старте бота."""
import os

import pytest
from telegram.ext import DictPersistence, PicklePersistence

from config import get_settings


@pytest.fixture
def state_file(monkeypatch):
    def set_path(value: str):
        monkeypatch.setattr(get_settings(), "state_file", value)
    return set_path


def test_file_on_writable_volume(state_file, tmp_path):
    from main import build_persistence

    state_file(str(tmp_path / "state" / "bot_state.pickle"))
    persistence = build_persistence()
    assert isinstance(persistence, PicklePersistence)
    assert (tmp_path / "state").is_dir()


def test_empty_state_file_is_discarded(state_file, tmp_path):
    """Пустой файл PTB не распаковывает и падает при старте — бот ушёл бы в цикл перезапусков."""
    from main import build_persistence

    path = tmp_path / "bot_state.pickle"
    path.touch()
    state_file(str(path))
    assert isinstance(build_persistence(), PicklePersistence)
    assert not path.exists()


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="права каталога не действуют на root/Windows")
def test_read_only_volume_falls_back_to_memory(state_file, tmp_path):
    from main import build_persistence

    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o555)
    try:
        state_file(str(read_only / "bot_state.pickle"))
        assert isinstance(build_persistence(), DictPersistence)
    finally:
        read_only.chmod(0o755)


def test_disabled_state_file(state_file):
    from main import build_persistence

    state_file("")
    assert isinstance(build_persistence(), DictPersistence)
