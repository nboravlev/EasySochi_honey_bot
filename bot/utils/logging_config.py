"""Логирование бота на stdlib logging.

- Файл `bot_structured.log` — JSON по строке на запись; формат читает log_viewer
  (timestamp, level, message, module, function, line, user_id, action, context, stack_trace…).
  Ротация по размеру.
- stdout — короткие строки для `docker logs`.
- Запись в файл и консоль идёт из отдельного потока через очередь, event loop не блокируется.
- Контекст апдейта (user_id, chat_id, update_id) ставится один раз на апдейт
  (`bind_update_context`) и попадает во все записи, сделанные при его обработке.

В коде используется `structured_logger.info(msg, user_id=…, action=…, context=…, exception=…)`.
"""
import atexit
import contextvars
import copy
import json
import logging
import logging.handlers
import queue
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "bot_structured.log"
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUPS = 5

# Поля, которые можно передать в structured_logger.*(); None не пишется
STRUCTURED_FIELDS = ("user_id", "session_id", "order_id", "action", "product_name", "execution_time", "context")

_update_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("log_update_context", default=None)
_listener: logging.handlers.QueueListener | None = None


def bind_update_context(**fields: Any) -> None:
    """Контекст текущего апдейта для всех последующих записей (вызывается в начале обработки)."""
    _update_context.set({k: v for k, v in fields.items() if v is not None})


class _ContextQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler, который сохраняет трейсбек и контекст апдейта.

    Стандартный prepare() вклеивает трейсбек в message и обнуляет exc_info,
    а contextvars в потоке-слушателе не видны — поэтому снимаем их здесь, в момент записи.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = copy.copy(record)
        record.message = record.getMessage()
        if record.exc_info and record.exc_info[0] is not None:
            record.stack_trace = "".join(traceback.format_exception(*record.exc_info))
        record.update_context = _update_context.get() or {}
        record.msg = record.message
        record.args = None
        record.exc_info = None
        record.exc_text = None
        return record


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        entry.update(getattr(record, "update_context", {}))
        # явно переданные поля важнее контекста апдейта
        entry.update(getattr(record, "structured", {}))
        stack_trace = getattr(record, "stack_trace", None)
        if stack_trace:
            entry["stack_trace"] = stack_trace
        return json.dumps(entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = {**getattr(record, "update_context", {}), **getattr(record, "structured", {})}
        tags = " ".join(f"{k}={fields[k]}" for k in ("action", "user_id", "order_id") if k in fields)
        if tags:
            line = f"{line} [{tags}]"
        stack_trace = getattr(record, "stack_trace", None)
        if stack_trace:
            line = f"{line}\n{stack_trace.rstrip()}"
        return line


class StructuredLogger:
    """Тонкая обёртка над logging.Logger с именованными полями.

    stacklevel=3 — чтобы module/function/line указывали на вызывающий код, а не на обёртку.
    """

    def __init__(self, name: str = "bot"):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, message: str, exception: BaseException | None = None, **fields: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        # неизвестные поля не роняют хендлер из-за опечатки в вызове лога — уходят в context
        unknown = {k: fields.pop(k) for k in list(fields) if k not in STRUCTURED_FIELDS}
        if unknown:
            fields["context"] = {**(fields.get("context") or {}), **unknown}
        structured = {k: v for k, v in fields.items() if v is not None}
        exc_info = (type(exception), exception, exception.__traceback__) if exception else None
        self._logger.log(level, message, exc_info=exc_info, extra={"structured": structured}, stacklevel=3)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, message, **kwargs)


structured_logger = StructuredLogger()


def flush_logs() -> None:
    """Останавливает поток записи, дописав очередь. Идемпотентна (QueueListener.stop — нет)."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


atexit.register(flush_logs)


def setup_logging(log_dir: str = "/app/logs", log_level: str = "INFO", enable_console: bool = True) -> None:
    """Настраивает корневой логгер. Повторный вызов заменяет прежнюю конфигурацию."""
    global _listener
    flush_logs()

    level = getattr(logging, str(log_level).upper(), logging.INFO)
    targets: list[logging.Handler] = []

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path / LOG_FILE_NAME, maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUPS, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        targets.append(file_handler)
    except OSError as exc:
        # без файла бот должен работать: остаётся консоль
        print(f"Log file is not available in {log_dir}: {exc}", file=sys.stderr)

    if enable_console or not targets:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(ConsoleFormatter())
        targets.append(console)

    log_queue: queue.SimpleQueue = queue.SimpleQueue()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_ContextQueueHandler(log_queue))
    root.setLevel(level)

    _listener = logging.handlers.QueueListener(log_queue, *targets, respect_handler_level=True)
    _listener.start()

    # httpx на INFO пишет URL каждого запроса к Bot API — вместе с токеном бота
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structured_logger.info(
        "Logging system initialized",
        action="logging_init",
        context={"log_dir": log_dir, "log_level": log_level},
    )
