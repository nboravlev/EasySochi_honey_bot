#!/usr/bin/env bash
# Бэкап базы honeybot: pg_dump (custom format) → $BACKUP_DIR, проверка читаемости, ротация;
# затем копия фото товаров → $BACKUP_DIR/media.
# При ошибке — сообщение в чат мониторинга. Запуск по cron, см. OPERATIONS.md.
#
# Переменные (необязательные): BACKUP_DIR (/data/easysochi/backups_honey), KEEP_DAYS (14),
#                              DB_CONTAINER (postgres_db_honey), BOT_CONTAINER (tg_bot_honey), ENV_FILE (<repo>/.env)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEEP_DAYS="${KEEP_DAYS:-14}"
target="$BACKUP_DIR/honey_$(date +%Y%m%d_%H%M%S).dump"

on_error() {
    log "backup FAILED (line $1)"
    rm -f "$target.partial"
    notify "❌ Бэкап базы honeybot НЕ создан ($(hostname), $(date '+%d.%m %H:%M')). Смотрите лог бэкапа."
}
trap 'on_error $LINENO' ERR

mkdir -p "$BACKUP_DIR"
log "dump $DB_CONTAINER → $target"
# внутри контейнера: локальное подключение, пользователь и база — из его окружения (.env)
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$target.partial"

# архив должен читаться: pg_restore --list разбирает оглавление целиком
docker exec -i "$DB_CONTAINER" pg_restore --list < "$target.partial" > /dev/null
[ -s "$target.partial" ]
mv "$target.partial" "$target"

deleted=$(find "$BACKUP_DIR" -maxdepth 1 -name 'honey_*.dump' -mtime +"$KEEP_DAYS" -print -delete | wc -l)
log "backup ok: $target ($(du -h "$target" | cut -f1)); removed old: $deleted"

# Фото товаров (том bot_media_honey, /app/media в контейнере бота). Файл после записи не меняется
# (уникальное имя), поэтому копия просто пополняется. Читаем через контейнер бота — он владелец файлов.
# Неудача здесь не отменяет бэкап базы, но сообщается в чат.
media_backup="$BACKUP_DIR/media"
if mkdir -p "$media_backup" \
    && docker exec "$BOT_CONTAINER" tar -C /app/media -cf - . | tar -C "$media_backup" -xf -; then
    log "media ok: $(find "$media_backup" -type f | wc -l) files in $media_backup"
else
    log "media backup FAILED"
    notify "⚠️ Фото товаров honeybot не скопированы в бэкап ($(hostname), $(date '+%d.%m %H:%M')). Бэкап базы создан."
fi
