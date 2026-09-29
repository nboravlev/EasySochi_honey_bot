#!/bin/bash
# Готовность БД обеспечивает docker compose (depends_on: service_healthy),
# адрес БД собирает config.py из POSTGRES_* и DB_HOST/DB_PORT.
set -euo pipefail

case "${1:-}" in
  bot)
    exec python main.py
    ;;
  api)
    # HTTP API витрины; nginx (web_honey) проксирует на него /api/
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*" --no-server-header
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
