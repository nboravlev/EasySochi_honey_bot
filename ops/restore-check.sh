#!/usr/bin/env bash
# Проверка, что последний бэкап восстанавливается: поднимает временный PostgreSQL из того же
# образа, что и боевая БД, восстанавливает дамп, проверяет схему и данные, удаляет контейнер.
# Боевую базу не трогает. Результат — в чат мониторинга. Запуск раз в неделю по cron.
#
# Переменные: BACKUP_DIR, DB_CONTAINER, ENV_FILE (как в backup.sh); DUMP — конкретный файл вместо последнего
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# shellcheck disable=SC2012  # имена дампов создаёт backup.sh по шаблону honey_<дата>.dump
dump="${DUMP:-$(ls -1t "$BACKUP_DIR"/honey_*.dump 2>/dev/null | head -n 1 || true)}"
check="honey_restore_check_$$"

cleanup() { docker rm -f "$check" >/dev/null 2>&1 || true; }
fail() {
    log "restore check FAILED: $1"
    notify "❌ Проверка восстановления бэкапа honeybot не прошла: $1"
    cleanup
    exit 1
}
trap cleanup EXIT

[ -n "$dump" ] && [ -f "$dump" ] || fail "бэкапов в $BACKUP_DIR нет"
image="$(docker inspect -f '{{.Config.Image}}' "$DB_CONTAINER")" || fail "контейнер $DB_CONTAINER не найден"

log "restore $dump into temporary container ($image)"
docker run -d --name "$check" -e POSTGRES_PASSWORD=restore-check -e POSTGRES_DB=restore_check "$image" >/dev/null
for _ in $(seq 1 60); do
    # готовность: принимает подключения и init-скрипты отработали (сервер перезапускается после них)
    if docker exec "$check" pg_isready -U postgres -d restore_check >/dev/null 2>&1 \
        && docker logs "$check" 2>&1 | grep -q "PostgreSQL init process complete"; then
        break
    fi
    sleep 2
done
sleep 3
docker exec "$check" pg_isready -U postgres -d restore_check >/dev/null || fail "временный PostgreSQL не запустился"

if ! out=$(docker exec -i "$check" pg_restore -U postgres -d restore_check --no-owner --no-privileges < "$dump" 2>&1); then
    fail "pg_restore завершился с ошибками: $(echo "$out" | grep -m 3 -i error | tr '\n' ' ')"
fi

q() { docker exec "$check" psql -U postgres -d restore_check -tAc "$1"; }
revision=$(q "SELECT version_num FROM alembic_version" 2>/dev/null) || fail "в дампе нет alembic_version"
counts=$(q "SELECT 'пользователей ' || (SELECT count(*) FROM users) || ', заказов ' || (SELECT count(*) FROM orders) || ', товаров ' || (SELECT count(*) FROM products)") \
    || fail "не удалось прочитать таблицы"

size=$(du -h "$dump" | cut -f1)
log "restore check ok: $(basename "$dump") ($size), revision $revision, $counts"
notify "✅ Бэкап honeybot восстанавливается: $(basename "$dump") ($size), миграция $revision, $counts."
