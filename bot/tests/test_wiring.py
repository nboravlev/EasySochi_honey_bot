"""Сборка приложения и согласованность констант со схемой БД."""
import importlib.util
from pathlib import Path

from telegram.ext import BaseHandler, ConversationHandler

from domain.enums import OrderStatus

MIGRATION = Path(__file__).parents[1] / "alembic/versions/b1c2d3e4f5a6_money_precision_and_reference_data.py"


def all_handlers(app):
    for group in app.handlers.values():
        for handler in group:
            yield handler
            if isinstance(handler, ConversationHandler):
                yield from handler.entry_points
                yield from handler.fallbacks
                for state_handlers in handler.states.values():
                    yield from state_handlers


def test_application_builds_with_valid_handlers():
    from main import build_application

    app = build_application()
    handlers = list(all_handlers(app))
    assert len(handlers) > 40
    # раньше в fallbacks отклонения лежали строка и функция — теперь только хендлеры
    assert all(isinstance(h, BaseHandler) for h in handlers)


def test_order_status_ids_match_migration_seed():
    spec = importlib.util.spec_from_file_location("seed_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [row_id for row_id, _ in module.ORDER_STATUSES] == [status.value for status in OrderStatus]
