#!/bin/bash
set -euo pipefail

# Собираем DATABASE_URL из переменных .env
# Если DB_HOST не задан, используем значение по умолчанию db_honey
DB_HOST=${DB_HOST:-db_honey}
#DB_PORT=${POSTGRES_PORT:-5432}
DB_PORT=5432

# Формируем URL для алхимии/приложения
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:${DB_PORT}/${POSTGRES_DB}"

# Ждём доступности Postgres
echo "[entrypoint] Waiting for postgres at ${DB_HOST}:${DB_PORT}..."

# Используем PGPASSWORD, чтобы pg_isready не запрашивал пароль интерактивно
export PGPASSWORD=$POSTGRES_PASSWORD

until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  >&2 echo "[entrypoint] Postgres is unavailable - sleeping"
  sleep 1
done

echo "[entrypoint] Postgres is ready"

# Логика запуска
case "${1:-}" in
  bot)
    # Запускаем из рабочей директории /bot
    exec python main.py
    ;;
  alembic)
    shift
    exec alembic "$@"
    ;;
  *)
    # Если передана любая другая команда (например, /bin/bash)
    exec "$@"
    ;;
esac