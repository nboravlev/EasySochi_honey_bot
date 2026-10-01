# Тестовый контур honeybot

Копия боевого стека для проверки релизов перед выкаткой: свой тестовый бот, своя база, свои домены.

| | Боевой контур | Тестовый контур |
|---|---|---|
| Данные (база, фото, логи) | отдельный диск RAID5: `/data/easysochi/…` | **тот же диск**, что и приложение: каталог `DATA_DIR` |
| Бэкапы | `/data/easysochi/backups_honey` | `BACKUP_DIR` из `.env` |
| Витрина и админка | `honey.easy-sochi.ru` | `test.easy-sochi.ru` → `127.0.0.1:8190` |
| Лог-вьюер | только SSH-туннель | `test-logger.easy-sochi.ru` → `127.0.0.1:8180`, **с паролем** (basic-auth) |
| Бот | боевой | **отдельный** тестовый бот из @BotFather |
| Проект / контейнеры / образы | `easysochi_honey_bot`, `tg_bot_honey`…, `honeybot/*` | `easysochi_honey_bot_test`, `test_tg_bot_honey`…, `honeybot-test/*` |
| Порты на хосте (БД / витрина / лог-вьюер) | 5335 / 8090 / 8080 | 5435 / 8190 / 8180 |

Отличия задаёт `deploy/test/docker-compose.override.yml` поверх общего `docker-compose.yml`;
сборка и запуск — тем же скриптом `ops/deploy.sh`, что и на бою. Имена, тома, сеть, порты и метки
`:latest` у теста свои, поэтому он может жить и на отдельном сервере, и на одном сервере с боевым контуром.

---

## 1. Что нужно на сервере

- Docker Engine и плагин Docker Compose v2 (`docker compose version`), пользователь в группе `docker`.
- `git`, `curl` (уведомления скриптов в Telegram), `bash`.
- Внешний nginx-шлюз с HTTPS (тот же, что для боевых доменов, или свой) — шаг 5.
- DNS: A-записи `test.easy-sochi.ru` и `test-logger.easy-sochi.ru` → IP тестового сервера.
- Свободное место: образы ≈ 2 ГБ (×3 последних сборки) плюс данные.

## 2. Код и каталоги данных

Отдельного диска нет — данные лежат на том же диске, что и приложение. Пример раскладки:

```
/srv/honeybot-test/
├── app/          ← репозиторий
├── data/         ← DATA_DIR
│   ├── postgres_honey/
│   ├── media_honey/
│   └── logs_honey/
└── backups/      ← BACKUP_DIR
```

```bash
sudo mkdir -p /srv/honeybot-test/data/{postgres_honey,media_honey,logs_honey} /srv/honeybot-test/backups
# бот, API и лог-вьюер работают под UID 1000; каталог базы PostgreSQL настроит сам при первом запуске
sudo chown -R 1000:1000 /srv/honeybot-test/data/media_honey /srv/honeybot-test/data/logs_honey
sudo chown "$USER": /srv/honeybot-test /srv/honeybot-test/backups
sudo chmod 750 /srv/honeybot-test/data

git clone git@github.com:nboravlev/EasySochi_honey_bot.git /srv/honeybot-test/app
cd /srv/honeybot-test/app
git checkout <ветка для проверки>
```

Фото в бэкап копируются через контейнер бота, поэтому пользователю, который запускает выкатку,
нужен доступ только к каталогу `backups` (и к репозиторию), а не к `data/`.

## 3. Подключить тестовый override

Compose сам добавляет `docker-compose.override.yml`, лежащий рядом с `docker-compose.yml`.
В репозитории файл хранится в `deploy/test/` (чтобы не подхватиться на боевом сервере),
на тестовом — ссылка из корня (один раз; в git она не попадёт — она в `.gitignore`):

```bash
ln -s deploy/test/docker-compose.override.yml docker-compose.override.yml
```

После этого и `ops/deploy.sh`, и любые `docker compose …` в этом каталоге работают с тестовым контуром;
скрипт пишет в начале «контур: тестовый».

## 4. `.env` и тестовый бот

```bash
cp deploy/test/.env.example .env
chmod 600 .env
nano .env
```

Обязательно поменять:

- `BOT_TOKEN` — **новый тестовый бот** (@BotFather → `/newbot`). Токен боевого бота использовать нельзя:
  Telegram отдаёт обновления только одному процессу, бой и тест будут «отнимать» сообщения друг у друга.
- `ADMIN_CHAT_ID` — тестовая группа продавцов (добавить в неё тестового бота), `DB_MONITOR_CHAT_ID` — чат
  для сообщений о выкатках и бэкапах (можно ту же группу), `OWNER_ID` — ваш Telegram ID.
- `POSTGRES_PASSWORD` — свой пароль; `DATA_DIR` / `BACKUP_DIR` — если раскладка не как в шаге 2.
- `VK_*` — пусто (VK выключен) или отдельные тестовое приложение и сообщество VK.

`CONTAINER_PREFIX=test_` не менять: по нему скрипты `ops/` (бэкап, восстановление) находят контейнеры теста.

Тестовому боту в @BotFather: *Bot Settings → Configure Mini App* → адрес `https://test.easy-sochi.ru/`
(для ссылок `t.me/<бот>?startapp=…`); кнопки «Магазин» и «⚙️ Админка» бот поставит сам по `WEBAPP_URL`.

## 5. Шлюз: домены и HTTPS

Контейнеры слушают только `127.0.0.1` — наружу их выводит nginx-шлюз с сертификатами.
Telegram открывает Mini App только по `https`.

Пароль для лог-вьюера (в логах персональные данные покупателей — без пароля открывать нельзя):

```bash
sudo apt install apache2-utils           # утилита htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd-honey-test <имя>
```

Сертификаты (если шлюз — nginx на этом сервере с certbot):

```bash
sudo certbot certonly --nginx -d test.easy-sochi.ru -d test-logger.easy-sochi.ru
```

Конфигурация шлюза, например `/etc/nginx/sites-available/honey-test.conf`:

```nginx
# витрина, Mini App и админка
server {
    listen 443 ssl;
    server_name test.easy-sochi.ru;
    ssl_certificate     /etc/letsencrypt/live/test.easy-sochi.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/test.easy-sochi.ru/privkey.pem;

    client_max_body_size 16m;               # фото товаров из админки (до 15 МБ)
    # тестовый стенд не индексируем
    add_header X-Robots-Tag "noindex, nofollow" always;

    location / {
        proxy_pass http://127.0.0.1:8190;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# лог-вьюер — только с паролем
server {
    listen 443 ssl;
    server_name test-logger.easy-sochi.ru;
    ssl_certificate     /etc/letsencrypt/live/test.easy-sochi.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/test.easy-sochi.ru/privkey.pem;

    auth_basic           "honeybot test logs";
    auth_basic_user_file /etc/nginx/.htpasswd-honey-test;
    add_header X-Robots-Tag "noindex, nofollow" always;

    location / {
        proxy_pass http://127.0.0.1:8180;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;                 # поток логов в реальном времени
        proxy_read_timeout 1h;
    }
}

server {
    listen 80;
    server_name test.easy-sochi.ru test-logger.easy-sochi.ru;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/honey-test.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Порты `8190` / `8180` — значения `WEB_PORT` / `LOG_VIEWER_PORT` из `.env`. Если шлюз работает в Docker,
вместо `127.0.0.1` — адрес хоста из его контейнера (или общая docker-сеть и `test_web_honey:80`).

## 6. Запуск

```bash
./ops/deploy.sh
```

Скрипт проверит окружение, соберёт образы `honeybot-test/*` с тегом коммита, сделает бэкап базы
(со второго запуска), накатит миграции, поднимет стек и дождётся готовности. Первый запуск дольше:
сборка всех образов и все миграции на пустой базе. Флаги — `./ops/deploy.sh --help`
и OPERATIONS.md, раздел 1.

Проверка:

1. `docker compose ps` — все сервисы `healthy`, `test_migrate_honey` — `Exited (0)`.
2. `https://test.easy-sochi.ru/` — каталог (пустой, пока нет товаров); `…/api/health` → `{"status":"ok"}`.
3. `https://test-logger.easy-sochi.ru/` — просит пароль, после него — журнал.
4. Тестовому боту `/start`; владельцу в меню — «⚙️ Админка», `/admin` в личке — ссылка на
   `https://test.easy-sochi.ru/admin/`.
5. Завести товар (в боте или админке), оформить заказ из Mini App, подтвердить в тестовой группе.

## 7. Обновление и проверка релиза

```bash
cd /srv/honeybot-test/app
git fetch && git checkout <ветка> && git pull
./ops/deploy.sh
```

Хранятся три последние сборки (`docker images honeybot-test/bot`), откат — `./ops/deploy.sh --skip-build --tag <тег>`.

## 8. Бэкапы и cron (по желанию)

Перед каждой выкаткой скрипт сам делает бэкап в `BACKUP_DIR`. Для регулярных бэкапов и автоперезапуска
зависшего бота — те же строки cron, что на бою (OPERATIONS.md, раздел 4), с путём к тестовому репозиторию
и логом в `BACKUP_DIR`:

```cron
15 3 * * *   /srv/honeybot-test/app/ops/backup.sh >> /srv/honeybot-test/backups/ops.log 2>&1
*/5 * * * *  /srv/honeybot-test/app/ops/restart-if-unhealthy.sh >> /srv/honeybot-test/backups/ops.log 2>&1
```

Скрипты читают `CONTAINER_PREFIX` и `BACKUP_DIR` из `.env` и работают с контейнерами теста.

## 9. Сбросить тестовые данные

Полностью очистить базу, фото и логи (бот, товары, заказы — всё заново):

```bash
docker compose down
sudo rm -rf /srv/honeybot-test/data/{postgres_honey,media_honey,logs_honey}/*
docker volume rm easysochi_honey_bot_test_bot_state_honey   # состояние диалогов бота
./ops/deploy.sh --no-backup
```

Загрузить копию боевой базы (например, чтобы проверить миграции на реальных данных) —
`./ops/restore.sh <дамп с боя>`: скрипт подтвердит действие, сделает страховочный бэкап тестовой базы,
восстановит дамп и накатит миграции. В копии — персональные данные покупателей: доступ к тестовому
серверу должен быть таким же закрытым, как к боевому, а тестовый бот не должен писать покупателям —
перед восстановлением отключите его (`docker compose stop bot_honey`) и после восстановления
очистите очередь уведомлений: `docker exec test_postgres_db_honey sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DELETE FROM notifications"'`.

## Частые вопросы

**Скрипт пишет «контур: боевой» на тестовом сервере.** Нет ссылки `docker-compose.override.yml` в корне — шаг 3.

**«нет каталогов данных».** Не созданы каталоги из шага 2 или `DATA_DIR` в `.env` указывает не туда.

**Бот перезапускается, в логах `InvalidToken`.** Неверный `BOT_TOKEN` в `.env`.

**Бот молчит, хотя контейнер healthy.** Тот же токен запущен где-то ещё (например, у разработчика локально):
Telegram отдаёт обновления только одному процессу.

**«API НЕ может писать в /app/media».** `sudo chown -R 1000:1000 <DATA_DIR>/media_honey`.

**Тест на одном сервере с боем.** Работает без доработок: имена, порты, тома и образы разные.
Шлюз у них общий — добавьте в него только серверы из шага 5.
