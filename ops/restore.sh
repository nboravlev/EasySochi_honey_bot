#!/usr/bin/env bash
# АВАРИЙНОЕ восстановление боевой базы из бэкапа. Заменяет ВСЕ текущие данные содержимым дампа.
#
#   ./ops/restore.sh /data/easysochi/backups_honey/honey_20260927_031500.dump
#
# Порядок: подтверждение → страховочный бэкап текущей базы → остановка бота, API и лог-вьюера →
#          пересоздание базы → pg_restore → миграции до версии кода (контейнер migrate_honey) → запуск.
# Переменные: DB_CONTAINER, BOT_CONTAINER, API_CONTAINER, VIEWER_CONTAINER, MIGRATE_CONTAINER, BACKUP_DIR,
#             ENV_FILE (имена — с CONTAINER_PREFIX из .env); YES=1 — без вопроса.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

dump="${1:-}"
[ -n "$dump" ] && [ -f "$dump" ] || { echo "Укажите файл дампа: $0 <файл.dump>"; exit 2; }

docker exec -i "$DB_CONTAINER" pg_restore --list < "$dump" > /dev/null || { echo "Файл не читается как дамп pg_dump"; exit 2; }

if [ "${YES:-}" != "1" ]; then
    echo "ВНИМАНИЕ: все текущие данные базы в $DB_CONTAINER будут заменены содержимым $(basename "$dump")."
    read -r -p "Для продолжения наберите RESTORE: " answer
    [ "$answer" = "RESTORE" ] || { echo "Отменено."; exit 1; }
fi

log "safety backup of the current database"
"$(dirname "$0")/backup.sh"

restart_apps() { docker start "$BOT_CONTAINER" "$API_CONTAINER" "$VIEWER_CONTAINER" >/dev/null 2>&1 || true; }
trap 'log "restore FAILED"; notify "❌ Восстановление базы honeybot из $(basename "$dump") не удалось — нужна ручная проверка."; restart_apps' ERR

log "stop $BOT_CONTAINER, $API_CONTAINER, $VIEWER_CONTAINER"
docker stop "$BOT_CONTAINER" "$API_CONTAINER" "$VIEWER_CONTAINER" >/dev/null 2>&1 || true

log "recreate database"
docker exec "$DB_CONTAINER" sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

log "pg_restore $(basename "$dump")"
docker exec -i "$DB_CONTAINER" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < "$dump"

# дамп мог быть сделан до последних миграций — догоняем схему до версии текущего кода
if docker inspect "$MIGRATE_CONTAINER" >/dev/null 2>&1; then
    log "migrations ($MIGRATE_CONTAINER)"
    docker start -a "$MIGRATE_CONTAINER"
else
    log "нет контейнера $MIGRATE_CONTAINER — миграции не применялись; выполните ops/deploy.sh --skip-build"
fi

revision=$(docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"')
restart_apps
trap - ERR
log "restore ok: $(basename "$dump"), alembic revision $revision"
notify "♻️ База honeybot восстановлена из $(basename "$dump") (миграция $revision). Бот перезапущен."
