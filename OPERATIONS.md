# Эксплуатация honeybot

Как выкатывать обновления, следить за ботом, делать бэкапы и восстанавливаться после аварии.
Все команды — на сервере, из каталога репозитория:

```bash
cd /home/easysochi/Projects/easysochi-bots/EasySochi_honey_bot
```

---

## 1. Выкатка обновления

1. Бэкап перед изменениями (занимает секунды):
   ```bash
   ./ops/backup.sh
   ```
2. Новый код:
   ```bash
   git pull
   ```
3. Миграции (если в релизе они есть; повторный запуск безопасен — применяются только новые):
   ```bash
   docker compose run --rm bot_honey alembic upgrade head
   ```
4. Пересборка и перезапуск:
   ```bash
   docker compose up -d --build
   ```
5. Проверка через минуту — у бота должно быть `(healthy)`:
   ```bash
   docker compose ps
   docker compose logs --tail 50 bot_honey
   ```
6. Короткая ручная проверка в Telegram: `/start`, меню открывается.

Миграцию и новый код выкатывайте вместе: код одного релиза рассчитан на схему базы того же релиза.

---

## 2. Как понять, что бот жив

**Healthcheck.** Бот каждые 30 секунд обновляет файл `/tmp/bot_heartbeat` внутри контейнера.
Docker проверяет его раз в минуту; если файлу больше 3 минут (бот завис), контейнер помечается `unhealthy`:

```bash
docker compose ps                         # колонка STATUS: Up … (healthy) / (unhealthy)
docker inspect -f '{{.State.Health.Status}}' tg_bot_honey
```

Сам Docker unhealthy-контейнер **не перезапускает** — это делает `ops/restart-if-unhealthy.sh` по cron (раздел 6).
Если процесс бота падает целиком, контейнер перезапускается сам (`restart: unless-stopped`).

**Логи.** `docker compose logs -f bot_honey` — предупреждения и ошибки; полный журнал в JSON —
`/data/easysochi/logs_honey/bot_structured.log` (и в лог-вьюере через SSH-туннель, см. README).

---

## 3. Сообщения в чате мониторинга

Все служебные сообщения приходят в чат `DB_MONITOR_CHAT_ID` из `.env`.

| Сообщение | Что значит | Что делать |
|---|---|---|
| 🐝 База данных доступна | плановое «всё хорошо», раз в `DB_MONITOR_HEARTBEAT_MINUTES` (30) минут | ничего; `0` в `.env` отключает эти сообщения |
| 🚨 База данных недоступна! | бот не может выполнить запрос к БД (проверка раз в минуту) | `docker compose ps`, `docker compose logs db_honey` |
| ✅ База данных снова доступна | БД восстановилась | ничего |
| ❌ Бэкап НЕ создан | ночной `backup.sh` упал | смотреть `ops.log` (раздел 4), запустить `./ops/backup.sh` вручную |
| ✅ Бэкап восстанавливается | еженедельная проверка прошла: дамп, миграция, число пользователей/заказов/товаров | сверить цифры с ожидаемыми |
| ❌ Проверка восстановления не прошла | последний дамп не восстанавливается | срочно: `./ops/backup.sh`, затем `./ops/restore-check.sh` вручную |
| ⚠️ Бот не отвечал и был перезапущен | зависание, сработал автоперезапуск | если повторяется — смотреть логи перед перезапуском |
| ♻️ База восстановлена из … | выполнено аварийное восстановление | проверить бота |

Скрипты `ops/*.sh` берут токен бота и ID чата из `.env`; если отправка не удалась, сообщение остаётся в `ops.log`.

---

## 4. Бэкапы

`ops/backup.sh` делает `pg_dump` (формат custom — сжатый, восстанавливается выборочно) в
`/data/easysochi/backups_honey/honey_ГГГГММДД_ЧЧММСС.dump`, проверяет, что архив читается,
и удаляет дампы старше 14 дней (`KEEP_DAYS`). Боевую работу бота не прерывает.

Затем копирует фото товаров в `/data/easysochi/backups_honey/media/` (через контейнер бота — он владелец
файлов). Фото после записи не меняются, поэтому копия просто пополняется. Если бот остановлен и фото
скопировать не удалось, бэкап базы всё равно создаётся, а в чат приходит предупреждение.

### Однократная настройка

```bash
sudo mkdir -p /data/easysochi/backups_honey
sudo chown easysochi: /data/easysochi/backups_honey
./ops/backup.sh                                   # проверить, что работает
ls -lh /data/easysochi/backups_honey
```

Расписание — `crontab -e` от пользователя `easysochi` (он должен запускать `docker` без `sudo`):

```cron
# honeybot: бэкап каждую ночь, проверка восстановления по воскресеньям, автоперезапуск зависшего бота
15 3 * * *   /home/easysochi/Projects/easysochi-bots/EasySochi_honey_bot/ops/backup.sh >> /data/easysochi/backups_honey/ops.log 2>&1
30 4 * * 0   /home/easysochi/Projects/easysochi-bots/EasySochi_honey_bot/ops/restore-check.sh >> /data/easysochi/backups_honey/ops.log 2>&1
*/5 * * * *  /home/easysochi/Projects/easysochi-bots/EasySochi_honey_bot/ops/restart-if-unhealthy.sh >> /data/easysochi/backups_honey/ops.log 2>&1
```

Проверить, что cron работает, — на следующий день: `tail /data/easysochi/backups_honey/ops.log`.

### Копия вне сервера

RAID5 защищает от выхода из строя одного диска, но **не** от удаления данных, ошибочной миграции,
шифровальщика или потери сервера. Дампы стоит регулярно копировать в другое место — на другую машину
(`rsync`) или в облачное хранилище (`rclone` в Yandex Object Storage / S3). Размер дампа — килобайты–мегабайты.

---

## 5. Проверка восстановления

Бэкап, который ни разу не восстанавливали, — не бэкап. `ops/restore-check.sh` раз в неделю:

1. берёт последний дамп;
2. поднимает **временный** PostgreSQL из того же образа, что боевая БД;
3. восстанавливает дамп и проверяет версию миграций и число пользователей, заказов, товаров;
4. удаляет временный контейнер и пишет результат в чат.

Боевую базу не трогает. Вручную: `./ops/restore-check.sh`, конкретный файл — `DUMP=/путь/к/файлу.dump ./ops/restore-check.sh`.

---

## 6. Аварийное восстановление базы

Когда нужно: данные испорчены или удалены, неудачная миграция, переезд на новый сервер.

```bash
ls -lt /data/easysochi/backups_honey | head                 # выбрать дамп
./ops/restore.sh /data/easysochi/backups_honey/honey_20260927_031500.dump
```

Скрипт попросит набрать `RESTORE`, затем:
1. сделает **страховочный бэкап** текущей базы (к нему можно вернуться тем же скриптом);
2. остановит бота и лог-вьюер;
3. пересоздаст базу и восстановит в неё дамп;
4. запустит бота и лог-вьюер, напишет в чат.

Если дамп сделан до последних миграций, после восстановления:

```bash
docker compose run --rm bot_honey alembic upgrade head
docker compose restart bot_honey
```

**Новый сервер:** развернуть проект по README (без `alembic upgrade`), скопировать дамп,
выполнить `./ops/restore.sh <дамп>`, затем `alembic upgrade head` и `docker compose up -d`.

**Фото товаров** восстанавливаются отдельно — копированием из бэкапа в том бота (бот должен быть запущен):

```bash
tar -C /data/easysochi/backups_honey/media -cf - . | docker exec -i tg_bot_honey tar -C /app/media -xf -
```

Фото, которых нет ни в хранилище, ни в бэкапе, бот отправляет по старому Telegram `file_id`, пока тот действителен.

---

## 7. Сохранение диалогов между перезапусками

Бот запоминает, на каком шаге диалога находится каждый пользователь (регистрация, оформление заказа,
ввод цены, рассылка), и его временные данные. Всё это хранится в файле `/app/state/bot_state.pickle`
на томе Docker `bot_state_honey` и сбрасывается на диск раз в минуту и при остановке.
После деплоя или перезапуска люди продолжают с того же шага.

- Том создаётся Docker автоматически, подготовка сервера не нужна.
- Отключить: `STATE_FILE=` (пусто) в `.env` — состояние только в памяти.
- Если каталог недоступен для записи, бот работает, но пишет в лог предупреждение `persistence_unavailable`.
- Таймауты диалогов после перезапуска не восстанавливаются: «забытый» диалог закроется, когда
  человек нажмёт `/start`, `/cancel` или кнопку другого сценария.
- Сбросить все диалоги (например, если файл повреждён и бот не стартует):
  ```bash
  docker compose stop bot_honey
  docker volume ls | grep bot_state_honey          # точное имя тома: <проект>_bot_state_honey
  docker volume rm <имя тома>
  docker compose up -d bot_honey
  ```

---

## 8. Переменные `.env`, относящиеся к эксплуатации

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DB_MONITOR_CHAT_ID` | прежний канал | куда писать мониторинг, бэкапы, перезапуски |
| `DB_MONITOR_HEARTBEAT_MINUTES` | `30` | «база доступна» раз в N минут; `0` — только при смене состояния |
| `STATE_FILE` | `/app/state/bot_state.pickle` | файл состояния диалогов; пусто — не сохранять |
| `MEDIA_DIR` | `/app/media` | фото товаров (том `bot_media_honey`) |
| `STOREFRONT_SHOP` | `kraspolhoney` | slug магазина-витрины; пусто — маркетплейс (каталог всех магазинов) |
| `LOG_LEVEL` | `INFO` | подробность логов |
| `SLOW_QUERY_MS` | `500` | порог медленного SQL-запроса для лога |

Переменные скриптов `ops/` (задаются перед командой, например `KEEP_DAYS=30 ./ops/backup.sh`):
`BACKUP_DIR` (`/data/easysochi/backups_honey`), `KEEP_DAYS` (`14`), `DB_CONTAINER` (`postgres_db_honey`),
`BOT_CONTAINER` (`tg_bot_honey`), `ENV_FILE` (`.env` в корне репозитория).

---

## 9. Магазины, уведомления, фото

Пока нет админ-панели, магазины и их служебные чаты настраиваются SQL-запросами. Консоль базы:

```bash
docker exec -it postgres_db_honey sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

### Сменить служебный чат магазина

Служебный чат — Telegram-группа, куда приходят новые заказы и где их подтверждают. Бот должен быть
в группе. ID группы — в логах бота (`chat_id`) или через @getidsbot.

```sql
UPDATE shop_channels SET address = '-1001234567890'
 WHERE shop_id = (SELECT id FROM shops WHERE slug = 'kraspolhoney')
   AND provider = 'telegram' AND purpose = 'staff';
```

Если группу превратили в супергруппу, бот обновит адрес сам при первой отправке.
Сменить `ADMIN_CHAT_ID` в `.env` недостаточно — он используется только при первом запуске.

### Добавить магазин

```sql
INSERT INTO shops (slug, name, contact_phone) VALUES ('adler-honey', 'Мёд Адлера', '+79880000000') RETURNING id;
-- точка выдачи: долгота, затем широта
INSERT INTO shop_locations (shop_id, name, address, point)
VALUES (2, 'Склад', 'Адлер, ул. Ленина, 1', ST_SetSRID(ST_MakePoint(39.92, 43.43), 4326));
INSERT INTO shop_channels (shop_id, provider, address) VALUES (2, 'telegram', '-1001234567890');
```

Менеджера назначает владелец в боте: `/manager_add @username adler-honey`.
Товары нового магазина видны покупателям, только если `STOREFRONT_SHOP` пуст (режим маркетплейса).

### Очередь уведомлений

Сообщения покупателям и в служебные чаты идут через таблицу `notifications`. Если Telegram не ответил,
бот повторяет отправку через 30 с, 2, 10, 30 минут, 1 и 3 часа, затем помечает строку `failed`.
Бот заблокирован или чат не найден — `failed` сразу. В логах: `notify_failed` (каждая неудача),
`notify_retry_batch` (досылка), `notify_no_channel` (получателю некуда писать).

```sql
-- сколько в каком статусе
SELECT status, count(*) FROM notifications GROUP BY status;
-- что не доставлено за сутки и почему
SELECT id, kind, user_id, shop_id, attempts, last_error, created_at
  FROM notifications WHERE status = 'failed' AND created_at > now() - interval '1 day' ORDER BY id DESC;
-- отправить повторно (например, после того как бота добавили в группу)
UPDATE notifications SET status = 'pending', attempts = 0, next_attempt_at = now() WHERE id = 123;
```

Отправленные строки хранятся 30 дней, неотправленные — 90, затем удаляются автоматически.

### Фото товаров

Файлы — в `/data/easysochi/media_honey` (в контейнере `/app/media`), в таблице `images` — ключ файла
(`storage_key`) и кэш Telegram (`tg_file_id`). Каталог на хосте должен принадлежать `1000:1000`:
иначе бот принимает фото, но не сохраняет файл (в логе `media_store_failed`).

После старта бот один раз скачивает в хранилище фото, которые есть только в Telegram
(лог `media_backfill`: сколько перенесено и сколько не удалось). Проверка:

```sql
SELECT count(*) FILTER (WHERE storage_key IS NOT NULL) AS in_storage,
       count(*) FILTER (WHERE storage_key IS NULL) AS only_telegram
  FROM images;
```

---

## 10. Однократно: выкатка «фазы А» (магазины, пользователи платформ, очередь, фото)

Релиз меняет схему существенно: 4 миграции (`d3e4f5a6b7c8` → `a6b7c8d9e0f1`). Порядок — как в разделе 1, плюс:

1. **Бэкап обязателен** (`./ops/backup.sh`): миграции переносят ссылки на пользователей с Telegram ID на `users.id`.
2. Проверить владельца каталога фото: `ls -ld /data/easysochi/media_honey` → `1000 1000`
   (если нет — `sudo chown -R 1000:1000 /data/easysochi/media_honey`).
3. В `.env` ничего менять не нужно: `STOREFRONT_SHOP` по умолчанию `kraspolhoney` — магазин,
   который создаёт миграция из текущих данных (точка выдачи «Пасека», Красная Поляна).
4. После `docker compose up -d --build` в логе бота должны быть `storefront_bootstrap`
   (служебный чат и телефон перенесены из `ADMIN_CHAT_ID` / `SELLER_CONTACT` в БД) и, через минуту,
   `media_backfill`.
5. Ручная проверка: заказ от тестового покупателя приходит в служебный чат, «Подтвердить» работает,
   покупателю приходит уведомление; в «Мой мёд» у менеджера видны фото.

Откат: `alembic downgrade c2d3e4f5a6b7` возвращает прежнюю схему, пока в системе нет пользователей
без Telegram (сайт, VK) и фото, загруженных только в хранилище; иначе — восстановление из бэкапа (раздел 6).
