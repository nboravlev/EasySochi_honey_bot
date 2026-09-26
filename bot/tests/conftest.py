"""Тестовое окружение: переменные задаются до импорта модулей бота (они читают настройки при импорте)."""
import os
import tempfile

TEST_ENV = {
    "BOT_TOKEN": "123456:TEST",
    "ADMIN_CHAT_ID": "-100500",
    "OWNER_ID": "42",
    "MANAGER_LIST": "111,222",
    "SELLER_CONTACT": "+70000000000",
    "POSTGRES_USER": "honey",
    "POSTGRES_PASSWORD": "secret",
    "POSTGRES_DB": "honey",
    "DB_HOST": "localhost",
    "LOG_DIR": tempfile.mkdtemp(prefix="honey-logs-"),
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)
