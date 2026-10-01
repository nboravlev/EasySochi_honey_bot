#!/usr/bin/env bash
#
# Сборка и запуск honeybot (бой или тестовый контур).
#
# По шагам:
#   1. предпроверки: Docker, .env и обязательные переменные, каталоги данных, корректность compose;
#      контур — тестовый, если в корне репозитория есть docker-compose.override.yml (deploy/test/README.md)
#   2. тег образов: короткий хеш коммита (+ -dirty, если есть незакоммиченные правки)
#   3. бэкап базы перед миграциями (ops/backup.sh), если база уже запущена
#   4. сборка образов с этим тегом и метка :latest
#   5. уборка старых образов: у каждого своего образа остаются последние --keep тегов (по умолчанию 3)
#   6. запуск: docker compose up -d — сначала migrate_honey (alembic upgrade head), затем бот и API
#   7. ожидание healthy и проверки: API отвечает через nginx витрины, API может писать фото
#
# При ошибке печатает диагностику: состояние контейнеров, лог миграций, хвосты логов упавших сервисов.
# Запуск — из любого каталога: ./ops/deploy.sh [опции]; справка: ./ops/deploy.sh --help
#
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$REPO_DIR"

KEEP_IMAGES=3
TAG=""
NO_CACHE=0
PULL=0
SKIP_BUILD=0
BACKUP=1
HEALTH_TIMEOUT=300

# сервисы с healthcheck (у лог-вьюера он в Dockerfile); migrate_honey — одноразовый, проверяется отдельно
HEALTHCHECKED="db_honey bot_honey api_honey web_honey log-viewer_honey"

usage() {
    cat <<EOF
Использование: $(basename "$0") [опции]

Собирает образы, накатывает миграции, поднимает стек и ждёт готовности сервисов.

Опции:
  --tag <тег>        тег образов (по умолчанию — короткий хеш коммита, с -dirty при правках)
  --skip-build       не собирать: поднять уже собранные образы с тегом --tag (откат, перезапуск)
  --no-cache         собрать без кеша Docker
  --pull             при сборке обновить базовые образы (python, node, nginx, postgres)
  --keep <N>         сколько последних тегов каждого образа хранить (по умолчанию $KEEP_IMAGES)
  --no-backup        не делать бэкап базы перед миграциями
  --timeout <сек>    сколько ждать готовности сервисов (по умолчанию $HEALTH_TIMEOUT)
  -h, --help         эта справка

Примеры:
  $(basename "$0")                              обычная выкатка текущего коммита
  $(basename "$0") --pull --no-cache            полная пересборка с обновлёнными базовыми образами
  $(basename "$0") --skip-build --tag 1a2b3c4   откат на сборку 1a2b3c4 (см. OPERATIONS.md, раздел 1)

Контур: тестовый, если в корне есть docker-compose.override.yml (ссылка на deploy/test/…), иначе боевой.
EOF
}

need_value() {
    if [ -z "${2:-}" ] || [ "${2#--}" != "$2" ]; then
        echo "Опция $1 требует значения." >&2
        exit 2
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h | --help) usage; exit 0 ;;
        --tag) need_value "$1" "${2:-}"; TAG=$2; shift 2 ;;
        --keep) need_value "$1" "${2:-}"; KEEP_IMAGES=$2; shift 2 ;;
        --timeout) need_value "$1" "${2:-}"; HEALTH_TIMEOUT=$2; shift 2 ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        --no-cache) NO_CACHE=1; shift ;;
        --pull) PULL=1; shift ;;
        --no-backup) BACKUP=0; shift ;;
        *) echo "Неизвестный аргумент: $1" >&2; echo >&2; usage >&2; exit 2 ;;
    esac
done

case "$KEEP_IMAGES" in '' | *[!0-9]*) echo "--keep: нужно целое число" >&2; exit 2 ;; esac
case "$HEALTH_TIMEOUT" in '' | *[!0-9]*) echo "--timeout: нужно целое число секунд" >&2; exit 2 ;; esac
if [ "$KEEP_IMAGES" -lt 1 ]; then
    echo "--keep: минимум 1 — иначе удалится только что собранный образ" >&2
    exit 2
fi
if [ "$SKIP_BUILD" -eq 1 ] && { [ "$NO_CACHE" -eq 1 ] || [ "$PULL" -eq 1 ]; }; then
    echo "--no-cache и --pull не имеют смысла вместе с --skip-build" >&2
    exit 2
fi

# ----------------------------------------------------------------- оформление

if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
step() { printf "\n%s==> %s%s\n" "$BOLD" "$1" "$RESET"; }
ok() { printf "%s  ok%s    %s\n" "$GREEN" "$RESET" "$1"; }
warn() { printf "%s  !!%s    %s\n" "$YELLOW" "$RESET" "$1"; }
fail() { printf "%s  FAIL%s  %s\n" "$RED" "$RESET" "$1" >&2; }

container_of() { docker compose ps -a -q "$1" 2>/dev/null | head -n 1; }

dump_diagnostics() {
    printf "\n%s=== Диагностика ===%s\n" "$RED" "$RESET"
    printf "\n--- docker compose ps -a ---\n"
    docker compose ps -a || true

    local id
    id=$(container_of migrate_honey)
    if [ -n "$id" ]; then
        printf "\n--- миграции (migrate_honey), код выхода %s ---\n" \
            "$(docker inspect -f '{{.State.ExitCode}}' "$id" 2>/dev/null || echo '?')"
        docker logs --tail 40 "$id" 2>&1 || true
    fi

    local service status health
    for service in $HEALTHCHECKED; do
        id=$(container_of "$service")
        [ -n "$id" ] || continue
        status=$(docker inspect -f '{{.State.Status}}' "$id" 2>/dev/null || echo "?")
        health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$id" 2>/dev/null || echo "?")
        if [ "$status" != "running" ] || [ "$health" = "unhealthy" ] || [ "$health" = "starting" ]; then
            printf "\n--- %s (status=%s, health=%s), последние 50 строк ---\n" "$service" "$status" "$health"
            docker logs --tail 50 "$id" 2>&1 || true
        fi
    done
    printf "\nПолные логи: docker compose logs <сервис> --tail 200\n"
}

on_exit() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        dump_diagnostics
        notify "❌ Выкатка honeybot ($CONTOUR, тег ${TAG:-?}) не удалась на $(hostname). Смотрите вывод ops/deploy.sh." || true
    fi
    exit "$rc"
}

# ----------------------------------------------------------------- 1. предпроверки

step "Предварительные проверки"

if ! docker info >/dev/null 2>&1; then
    fail "демон Docker недоступен (запущен ли Docker? есть ли у пользователя доступ к нему?)"
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    fail "нет плагина docker compose (нужен Docker Compose v2)"
    exit 1
fi
ok "Docker и docker compose доступны"

if [ ! -f "$ENV_FILE" ]; then
    fail "нет файла $ENV_FILE"
    echo "  Создайте из шаблона: cp .env.example .env (тестовый контур — deploy/test/.env.example)" >&2
    exit 1
fi
ok ".env на месте"

# compose на отсутствующую переменную только предупреждает и подставляет пустую строку —
# база поднялась бы без пароля, порт опубликовался бы пустым. Проверяем заранее.
REQUIRED_VARS="BOT_TOKEN ADMIN_CHAT_ID POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT LOG_VIEWER_PORT"
missing=""
for var in $REQUIRED_VARS; do
    [ -n "$(env_get "$var")" ] || missing="$missing $var"
done
if [ -n "$missing" ]; then
    fail "в .env не заданы обязательные переменные:$missing"
    exit 1
fi
ok "обязательные переменные заданы"

if [ -e docker-compose.override.yml ]; then
    CONTOUR="тестовый"
    DATA_DIR=$(env_get DATA_DIR)
    if [ -z "$DATA_DIR" ] || [ "${DATA_DIR#/}" = "$DATA_DIR" ]; then
        fail "тестовый контур: в .env нужен DATA_DIR — абсолютный путь к каталогу данных"
        exit 1
    fi
    if [ "$(env_get CONTAINER_PREFIX)" != "test_" ]; then
        warn "CONTAINER_PREFIX в .env не test_ — бэкап и другие скрипты ops/ не найдут контейнеры теста"
    fi
else
    CONTOUR="боевой"
    DATA_DIR=/data/easysochi
fi
ok "контур: $CONTOUR, данные: $DATA_DIR"

# без каталога bind-том не смонтируется, и контейнер упадёт с невнятной ошибкой
missing=""
for dir in postgres_honey media_honey logs_honey; do
    [ -d "$DATA_DIR/$dir" ] || missing="$missing $DATA_DIR/$dir"
done
if [ -n "$missing" ]; then
    fail "нет каталогов данных:$missing"
    echo "  Подготовка каталогов: README.md («Пути на хосте») или deploy/test/README.md, шаг 2" >&2
    exit 1
fi
ok "каталоги данных на месте"

if ! errors=$(docker compose config -q 2>&1); then
    fail "docker compose config: конфигурация не собирается"
    echo "$errors" >&2
    exit 1
fi
ok "docker compose config — без ошибок"

# ----------------------------------------------------------------- 2. тег

if [ -z "$TAG" ]; then
    if [ "$SKIP_BUILD" -eq 1 ]; then
        TAG=latest
    elif git -C "$REPO_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
        TAG=$(git -C "$REPO_DIR" rev-parse --short HEAD)
        if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]; then
            TAG="${TAG}-dirty"
            warn "есть незакоммиченные правки — тег с суффиксом -dirty (сборку не повторить из коммита)"
        fi
    else
        TAG=latest
        warn "каталог не под git — тег latest"
    fi
fi
export TAG

# наши образы (репозиторий без тега) — только они участвуют в метках и уборке
IMAGES=$(docker compose config --images | sed 's/:[^:/]*$//' | sort -u)
ok "тег образов: $TAG"

# ----------------------------------------------------------------- 3. бэкап

DB_RUNNING=$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || echo false)
if [ "$BACKUP" -eq 0 ]; then
    step "Бэкап пропущен (--no-backup)"
elif [ "$DB_RUNNING" != "true" ]; then
    step "Бэкап пропущен: база $DB_CONTAINER не запущена (первый запуск?)"
else
    step "Бэкап базы перед миграциями"
    "$REPO_DIR/ops/backup.sh"
    ok "бэкап готов: $BACKUP_DIR"
fi

trap on_exit EXIT

# ----------------------------------------------------------------- 4. сборка

if [ "$SKIP_BUILD" -eq 1 ]; then
    step "Сборка пропущена (--skip-build): образы с тегом $TAG"
    for image in $IMAGES; do
        if ! docker image inspect "$image:$TAG" >/dev/null 2>&1; then
            fail "нет образа $image:$TAG — доступные теги: docker images $image"
            exit 1
        fi
    done
    ok "все образы $TAG на месте"
else
    step "Сборка образов ($TAG)"
    build_args=()
    [ "$NO_CACHE" -eq 1 ] && build_args+=(--no-cache)
    [ "$PULL" -eq 1 ] && build_args+=(--pull)
    # ${a[@]+…} — пустой массив под set -u в bash до 4.4 считается неопределённым
    docker compose build ${build_args[@]+"${build_args[@]}"}
    if [ "$TAG" != "latest" ]; then
        for image in $IMAGES; do
            docker tag "$image:$TAG" "$image:latest"
        done
        ok "образы помечены и как :latest (обычный docker compose up -d поднимет эту сборку)"
    fi
fi

# ----------------------------------------------------------------- 5. уборка старых образов

# Трогаем только свои репозитории (сервер общий). :latest и текущий тег не удаляем;
# образ, занятый контейнером, docker удалить откажется — это правильно.
step "Уборка старых образов (храним тегов каждого образа: $KEEP_IMAGES)"
removed=0
for image in $IMAGES; do
    old_tags=$(
        docker image ls "$image" --format '{{.CreatedAt}}|{{.Tag}}' |
            awk -F'|' -v tag="$TAG" '$2 != "latest" && $2 != "<none>" && $2 != tag' |
            sort -r |
            awk -v keep="$((KEEP_IMAGES - 1))" 'NR > keep' |
            cut -d'|' -f2
    )
    for old in $old_tags; do
        if docker rmi "$image:$old" >/dev/null 2>&1; then
            ok "удалён $image:$old"
            removed=$((removed + 1))
        else
            warn "не удалось удалить $image:$old — вероятно, используется контейнером"
        fi
    done
done
[ "$removed" -gt 0 ] || ok "удалять нечего"

# ----------------------------------------------------------------- 6. запуск и миграции

step "Запуск: миграции (alembic upgrade head), затем сервисы"
# migrate_honey выполняется до бота и API; если миграция упадёт, up завершится ошибкой,
# а бот и API останутся на прежней версии (их контейнеры не пересоздаются)
docker compose up -d --remove-orphans
migrate=$(container_of migrate_honey)
docker logs "$migrate" 2>&1 | grep -E "Running (upgrade|downgrade)|Context impl" | sed 's/^/        /' || true
ok "миграции применены (код выхода $(docker inspect -f '{{.State.ExitCode}}' "$migrate"))"

# ----------------------------------------------------------------- 7. готовность

wait_healthy() {
    local service=$1 id status started elapsed
    id=$(container_of "$service")
    if [ -z "$id" ]; then
        fail "$service: контейнер не создан"
        return 1
    fi
    started=$(date +%s)
    while true; do
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")
        elapsed=$(($(date +%s) - started))
        case "$status" in
            healthy) ok "$service — healthy (${elapsed} с)"; return 0 ;;
            unhealthy | exited | dead) fail "$service — $status через ${elapsed} с"; return 1 ;;
        esac
        if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
            fail "$service не стал healthy за ${HEALTH_TIMEOUT} с (статус: $status)"
            return 1
        fi
        sleep 3
    done
}

step "Ожидание готовности (до $HEALTH_TIMEOUT с; бот отчитывается раз в минуту)"
for service in $HEALTHCHECKED; do
    wait_healthy "$service"
done

step "Проверки"
web=$(container_of web_honey)
if health=$(docker exec "$web" wget -qO- http://127.0.0.1/api/health 2>&1) && [ "$health" = '{"status":"ok"}' ]; then
    ok "API отвечает через nginx витрины (/api/health)"
else
    fail "витрина не проксирует API: $health"
    exit 1
fi

MEDIA_WRITABLE=1
api=$(container_of api_honey)
if docker exec "$api" sh -c 'touch /app/media/.write-test && rm -f /app/media/.write-test' >/dev/null 2>&1; then
    ok "API пишет в /app/media — загрузка фото из админки работает"
else
    MEDIA_WRITABLE=0
    warn "API НЕ может писать в /app/media ($DATA_DIR/media_honey) — загрузка фото из админки упадёт"
    warn "  sudo chown -R 1000:1000 $DATA_DIR/media_honey"
fi

# ----------------------------------------------------------------- итог

trap - EXIT
step "Готово: контур $CONTOUR, сборка $TAG"
printf "  образы:          %s\n" "$(echo "$IMAGES" | tr '\n' ' ')"
printf "  доступные теги:  docker images %s\n" "$(echo "$IMAGES" | grep '/bot$' || echo "$IMAGES" | head -n 1)"
printf "  откат:           ./ops/deploy.sh --skip-build --tag <прежний тег>  (если между сборками были\n"
printf "                   миграции — сначала откатить схему, см. OPERATIONS.md, раздел 1)\n"
if [ "$MEDIA_WRITABLE" -eq 0 ]; then
    printf "\n"
    warn "загрузка фото из админки НЕ работает: нет прав на $DATA_DIR/media_honey"
fi
notify "✅ honeybot выкачен ($CONTOUR, сборка $TAG) на $(hostname)." || true
