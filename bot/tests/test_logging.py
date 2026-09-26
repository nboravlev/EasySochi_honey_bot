import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from utils import logging_config
from utils.logging_config import bind_update_context, setup_logging, structured_logger


@pytest.fixture
def log_file(tmp_path):
    setup_logging(log_dir=str(tmp_path), log_level="INFO", enable_console=False)
    yield tmp_path / logging_config.LOG_FILE_NAME
    bind_update_context()
    logging_config.flush_logs()


def read_entries(path: Path) -> list[dict]:
    logging_config.flush_logs()  # дожидаемся записи из очереди
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def emit_from_handler():
    structured_logger.info("новый заказ", action="order_created", order_id=7, context={"amount": Decimal("15000.00")})


def test_viewer_compatible_fields(log_file):
    emit_from_handler()
    entry = next(e for e in read_entries(log_file) if e["message"] == "новый заказ")
    assert entry["level"] == "INFO"
    assert entry["timestamp"].endswith("Z")
    assert entry["action"] == "order_created" and entry["order_id"] == 7
    assert entry["context"] == {"amount": "15000.00"}
    # module/function/line указывают на вызывающий код, а не на обёртку логгера
    assert (entry["module"], entry["function"]) == ("test_logging", "emit_from_handler")
    # незаданные поля не пишутся (log_viewer делает .lower() по action)
    assert "user_id" not in entry


def test_cyrillic_is_not_escaped(log_file):
    emit_from_handler()
    read_entries(log_file)
    assert "новый заказ" in log_file.read_text(encoding="utf-8")


def test_level_filter(log_file):
    structured_logger.debug("скрытая отладка")
    structured_logger.warning("видимое предупреждение")
    messages = [e["message"] for e in read_entries(log_file)]
    assert "видимое предупреждение" in messages
    assert "скрытая отладка" not in messages


def test_update_context_is_attached(log_file):
    bind_update_context(user_id=555, chat_id=555, update_id=1)
    structured_logger.info("внутри апдейта")
    entry = next(e for e in read_entries(log_file) if e["message"] == "внутри апдейта")
    assert (entry["user_id"], entry["chat_id"], entry["update_id"]) == (555, 555, 1)


def test_explicit_fields_override_update_context(log_file):
    bind_update_context(user_id=555)
    structured_logger.info("о другом пользователе", user_id=777)
    entry = next(e for e in read_entries(log_file) if e["message"] == "о другом пользователе")
    assert entry["user_id"] == 777


def test_exception_goes_to_stack_trace(log_file):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        structured_logger.error("ошибка", exception=exc)
    entry = next(e for e in read_entries(log_file) if e["message"] == "ошибка")
    assert "ValueError: boom" in entry["stack_trace"]


def test_unknown_fields_go_to_context_instead_of_crashing(log_file):
    structured_logger.info("опечатка в поле", commment="x")
    entry = next(e for e in read_entries(log_file) if e["message"] == "опечатка в поле")
    assert entry["context"] == {"commment": "x"}


def test_library_logs_are_captured_and_httpx_is_quiet(log_file):
    logging.getLogger("telegram.ext").error("ошибка библиотеки")
    logging.getLogger("httpx").info("POST https://api.telegram.org/bot<TOKEN>/getUpdates")
    messages = [e["message"] for e in read_entries(log_file)]
    assert "ошибка библиотеки" in messages
    assert not any("api.telegram.org" in m for m in messages)
