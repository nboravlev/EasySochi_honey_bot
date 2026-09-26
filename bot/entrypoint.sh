#!/bin/bash
# Готовность БД обеспечивает docker compose (depends_on: service_healthy),
# адрес БД собирает config.py из POSTGRES_* и DB_HOST/DB_PORT.
set -euo pipefail

case "${1:-}" in
  bot)
    exec python main.py
    ;;
  alembic)
    shift
    exec alembic "$@"
    ;;
  *)
    # любая другая команда, например /bin/bash
    exec "$@"
    ;;
esac
