"""Настройки приложения из переменных окружения (.env подключается docker compose).

Две группы:
- DatabaseSettings — нужны и боту, и Alembic;
- Settings — всё остальное, нужно только боту.
Разделены, чтобы `alembic upgrade` не требовал BOT_TOKEN и ID чатов.
"""
from functools import cached_property, lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class _Base(BaseSettings):
    # env_ignore_empty: «OWNER_ID=» в .env трактуется как «не задано», а не как ошибка
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)


class DatabaseSettings(_Base):
    postgres_user: str
    postgres_password: str
    postgres_db: str
    db_host: str = "db_honey"
    # порт внутри docker-сети; POSTGRES_PORT из .env — это порт на хосте, здесь он не нужен
    db_port: int = 5432

    sql_echo: bool = False       # SQL с параметрами в лог — только для локальной отладки
    slow_query_ms: int = 500     # запросы дольше порога пишутся в лог как WARNING

    @cached_property
    def database_url(self) -> str:
        # URL.create сам экранирует спецсимволы в пароле
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.db_host,
            port=self.db_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


class Settings(_Base):
    bot_token: str
    admin_chat_id: int
    owner_id: int | None = None
    # «111,222» или «[111, 222]»; только первичное заполнение users.role_id (services.users.bootstrap_managers)
    manager_list: str = ""
    seller_contact: str | None = None

    # мониторинг БД: при смене состояния (упала / восстановилась) — сообщение сразу;
    # плюс сообщение «база доступна» раз в N минут (0 — только при смене состояния)
    db_monitor_chat_id: int = -1002843679066
    db_monitor_heartbeat_minutes: int = 30

    log_dir: str = "/app/logs"
    log_level: str = "INFO"

    # диалоги и user_data между перезапусками (пустая строка — не сохранять)
    state_file: str = "/app/state/bot_state.pickle"
    # файл обновляется джобой каждые 30 с; по его свежести docker healthcheck судит, что бот не завис
    heartbeat_file: str = "/tmp/bot_heartbeat"

    @cached_property
    def manager_ids(self) -> frozenset[int]:
        """MANAGER_LIST плюс владелец — для первого запуска. Права проверяются по users.role_id."""
        ids = {int(part.strip(" []")) for part in self.manager_list.split(",") if part.strip(" []")}
        if self.owner_id:
            ids.add(self.owner_id)
        return frozenset(ids)


@lru_cache
def get_db_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
