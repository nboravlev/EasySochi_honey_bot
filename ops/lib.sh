#!/usr/bin/env bash
# Общие функции скриптов эксплуатации. Подключается через: source "$(dirname "$0")/lib.sh"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"

DB_CONTAINER="${DB_CONTAINER:-postgres_db_honey}"
BOT_CONTAINER="${BOT_CONTAINER:-tg_bot_honey}"
BACKUP_DIR="${BACKUP_DIR:-/data/easysochi/backups_honey}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Значение переменной из .env (без кавычек); пусто, если нет
env_get() {
    [ -f "$ENV_FILE" ] || return 0
    # «|| true»: отсутствие переменной — не ошибка (скрипты работают под set -euo pipefail)
    { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

# Сообщение в чат мониторинга (DB_MONITOR_CHAT_ID). Ошибка отправки не роняет скрипт.
notify() {
    local token chat
    token="$(env_get BOT_TOKEN)"
    chat="$(env_get DB_MONITOR_CHAT_ID)"
    chat="${chat:--1002843679066}"
    if [ -z "$token" ] || ! command -v curl >/dev/null 2>&1; then
        log "notify skipped (нет BOT_TOKEN или curl): $1"
        return 0
    fi
    curl -s -m 15 -o /dev/null "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1" || log "notify failed: $1"
}
