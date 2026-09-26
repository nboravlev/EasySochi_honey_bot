-- Выполняется один раз при инициализации пустого каталога данных PostgreSQL.
-- Таблицы и справочники создаёт Alembic (bot/alembic), здесь — только расширения.
CREATE EXTENSION IF NOT EXISTS postgis;
