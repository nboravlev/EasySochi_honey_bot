#!/usr/bin/env bash
# Docker помечает зависший бот как unhealthy (heartbeat старше 3 минут), но сам не перезапускает.
# Этот скрипт (cron раз в 5 минут) перезапускает контейнер и сообщает в чат мониторинга.
#
# Переменные: BOT_CONTAINER (tg_bot_honey), ENV_FILE
set -euo pipefail
source "$(dirname "$0")/lib.sh"

status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' \
    "$BOT_CONTAINER" 2>/dev/null) || { log "container $BOT_CONTAINER not found"; exit 0; }

if [ "$status" = "unhealthy" ]; then
    log "$BOT_CONTAINER is unhealthy — restarting"
    docker restart "$BOT_CONTAINER" >/dev/null
    notify "⚠️ Бот honeybot не отвечал (healthcheck) и был перезапущен ($(hostname), $(date '+%d.%m %H:%M'))."
fi
