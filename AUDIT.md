# Аудит EasySochi_honey_bot

Дата: 2026-09-26 · Ревизия: `cbe8215` (main)

Объём: ~8,9 тыс. строк (Python ~7 тыс.), 29 хендлеров, 18 утилит, 18 моделей, 9 миграций.
Тестов, линтеров и CI в репозитории нет.

Уровни: 🔴 критично (ломает прод, безопасность или деньги) · 🟠 важно · 🟡 желательно.

---

## 0. Главное

| # | Уровень | Что | Где |
|---|---|---|---|
| 1 | 🔴 | Любой пользователь может создать и опубликовать товар: у `/honey_add` и `confirm_product_*` нет проверки роли | `handlers/InsertProductHandler.py:5`, `handlers/ProductConfirmHandler.py:15` |
| 2 | 🔴 | С чистого клона проект не собирается: `db/Dockerfile` копирует `init/init-pg.sql`, а этот файл не попадает в git из-за `*.sql` в `.gitignore`. В репозитории нет и справочников (статусы, роли, размеры, тара), без которых бот не работает | `db/Dockerfile:12`, `.gitignore:32` |
| 3 | 🔴 | `orders.total_price NUMERIC(5,1)` вмещает максимум 9 999,9 ₽. Четыре банки по 3 000 ₽ дают необработанный `DataError` в `handle_update_quantity`, и заказ зависает | `db/models/orders.py:38`, `handlers/SelectProductConversation.py:329` |
| 4 | 🔴 | Лог-вьюер опубликован на `0.0.0.0` без авторизации, а в логах есть персональные данные: имена, username, тексты комментариев. PostgreSQL тоже проброшен на хост | `docker-compose.yml:8,39` |
| 5 | 🔴 | После регистрации диалог остаётся в состоянии `ASK_PHONE` на 5 минут. `/start` и любой текст в это время уходят в `handle_phone_registration`, а повторное «Пропустить» пытается ещё раз создать того же пользователя | `handlers/RegistrationConversation.py:348` |
| 6 | 🟠 | Кнопка «Использовать никнейм из ТГ» не работает никогда: условие инвертировано | `handlers/RegistrationConversation.py:223` |
| 7 | 🟠 | Кнопки навигации и фильтров в «Мои заказы» не работают: хендлер всегда возвращает `END`, в состояние `VIEW_ORDERS` диалог не попадает | `handlers/ManagerOrdersConversation.py:150` |
| 8 | 🟠 | В `fallbacks` диалога отклонения лежат строка и функция вместо хендлеров. `/cancel` не работает, а любая команда в этом состоянии падает с `AttributeError` | `handlers/DeclineCancelOrderHandler.py:8` |
| 9 | 🟠 | Черновики заказов (статус 8) создаются на каждый клик по размеру и никогда не истекают: джоба отключена и сломана (импортирует несуществующий `DrinkSize`). Из-за этого раздута статистика «Всего» | `check_expired_orders.py:5`, `main.py:75` |
| 10 | 🟠 | Логирование бота не инициализировано: `setup_logging()` вызывается только в FastAPI-приложении, которое не запускается. Необработанные исключения PTB не попадают ни в файл, ни во вьюер. `echo=True` пишет весь SQL в stdout | `api/main.py:15`, `db/db_async.py:17` |

---

## 1. Сборка и деплой

### 🔴 1.1 Сборка с чистого клона падает
- `db/Dockerfile:12` делает `COPY init/init-pg.sql`, но каталога `db/init/` нет в репозитории: правило `*.sql` в `.gitignore:32` его отсекает.
- Код жёстко завязан на ID справочников: статусы 1–8, роли 1–4, размеры `0.5/1.0/1.5`. При этом ни одна миграция их не создаёт, а начальная миграция (`7e3bc4973d6f`) осталась от кофейного бота.
- **Предложение:** перенести справочники в миграцию Alembic (`op.bulk_insert`), `init-pg.sql` сократить до `CREATE EXTENSION postgis` и закоммитить (добавить в `.gitignore` исключение `!db/init/*.sql`).

### 🔴 1.2 Миграции нельзя выполнить через entrypoint
- `entrypoint.sh:11` перезаписывает `DATABASE_URL` на `postgresql+asyncpg://…`, а `alembic/env.py:59` строит **синхронный** движок через `engine_from_config`. Команда `docker compose run bot_honey alembic upgrade head` упадёт.
- `DATABASE_URL_SYNC` из `.env` указывает на порт `5335`, то есть на порт хоста, а не на порт внутри сети (`5432`). `db/db.py` требует эту переменную уже при импорте любой модели.
- **Предложение:** одна переменная `DATABASE_URL`, из которой строятся оба варианта. `env.py` перевести на async-шаблон Alembic (`async_engine_from_config` + `run_sync`). `db/db.py` (синхронный движок) удалить: кроме Alembic, его никто не использует.

### 🟠 1.3 docker-compose
- `volumes: ./bot:/bot` поверх образа — это режим разработки в проде: образ фактически не используется, код берётся с хоста. Убрать.
- `ports: "${POSTGRES_PORT}:5432"` открывает БД на всех интерфейсах. Убрать или ограничить `127.0.0.1:${POSTGRES_PORT}:5432`.
- Лог-вьюер слушает `0.0.0.0` без авторизации (см. §4.5). Как минимум `127.0.0.1:` и доступ через nginx с basic-auth.
- В healthcheck БД не заданы `interval/retries`, по умолчанию 30 с: бот стартует медленно. Задать `interval: 5s`.
- Volume `bot_media_honey:/app/media` смонтирован, но в коде не используется.
- В `entrypoint.sh` цикл ожидания `pg_isready` дублирует `depends_on: service_healthy`, `postgresql-client` нужен только ради него. Цикл можно убрать.

### 🟠 1.4 Dockerfile
- `bot/.dockerignore` и `log_viewer/.dockerignore` не работают: в них текст вида `.env — особенно важно…` и `__pycache__, *.pyc`. Docker читает каждую строку как один шаблон, поэтому `.env`, `__pycache__` и `venv` **не исключаются**. Нужен нормальный формат, по одному шаблону на строку.
- `gcc` и `libpq-dev` не нужны: используются `psycopg2-binary` и `asyncpg` с готовыми колёсами. Их удаление заметно сократит образ, либо стоит сделать multi-stage.
- `ENV KEY value` — устаревший синтаксис, нужен `ENV KEY=value`.
- У бота Python 3.12, у лог-вьюера 3.11. Код бота опирается на 3.12 (f-строки с вложенными кавычками, `SelectProductConversation.py:290,358`), поэтому версию лучше выровнять.
- Нет `HEALTHCHECK` для бота. Хватит простой проверки живости процесса или файла-heartbeat, который обновляет джоба.

### 🟠 1.5 Зависимости
- `requirements.txt` получен через `pip freeze` и смешивает прямые зависимости с транзитивными. `numpy`, `shapely`, `uvloop`, `watchfiles`, `websockets`, `httptools`, `PyYAML`, `pytz`, `six` не нужны или нужны только мёртвому коду.
- `jinja2==3.1.0` — старая версия с известными CVE (исправлены в 3.1.3+ и 3.1.5+). `httpx==0.25.2` устарел. `Pillow>=10.0.0` не закреплён.
- `python-telegram-bot==20.7` устарел, актуальна ветка 21.x/22.x. Обновляться стоит после покрытия тестами.
- **Предложение:** `pyproject.toml` с прямыми зависимостями и lock-файл (`uv`/`pip-tools`), `ruff` и `pytest` в dev-группе.

### 🟡 1.6 Прочее
- README местами скопирован из проекта аренды: `db_rent`, `bot_rent`, `EasySochi_bot/`, `log_viewer/utils` (такого каталога нет), обещана доставка по зонам через MapBox (функции нет).
- В `db_monitor.py:12` жёстко прописан `CHAT_ID = -1002843679066`, хотя в `.env` есть `ADMIN_CHAT_ID`.
- Нет CI. Минимальный вариант — GitHub Actions: `ruff check`, `pytest`, `docker compose build`.

---

## 2. Бизнес-логика

### 🔴 2.1 Роли и права
Роль менеджера определяется в **четырёх** местах, и они не согласованы:
`MANAGER_LIST` (env) → меню; `OWNER_ID` (env) → «админ» в статистике и списках; `sessions.role_id` → просто запись; `products.created_by` → владение товаром. Таблица `roles` для авторизации не используется.

Последствия:
- `/honey_add` — открытая `CommandHandler`. Любой покупатель проходит сценарий, получает карточку с кнопкой «✅ Подтвердить» и публикует товар в каталог.
- `redo_product_*`, `product_delete_*`, `edit_sizeprice_*`, `honey_invite`, `confirm_order_*`, `order_ready_*`, `order_complit_*` не проверяют, кто нажал. Сейчас эти кнопки видят только менеджеры в админ-чате, но callback_data можно подделать модифицированным клиентом, а в админ-группе нажать может любой её участник.
- `OWNER_ID` видит все товары (`fetch_seller_products`), но редактировать цену может только автор (`ManagerProductsConversation.py:123`).

**Предложение:** хранить роль в `users.role_id`, а не в сессиях и env. Ввести декоратор `@require_role(Role.MANAGER)` и повесить его на все менеджерские хендлеры. В колбэках покупателя проверять `order.tg_user_id == effective_user.id`.

### 🔴 2.2 Жизненный цикл заказа: нет машины состояний
Переходы разбросаны по хендлерам, проверки статуса есть не везде:

| Переход | Проверка исходного статуса | Идемпотентность |
|---|---|---|
| `pay_*` DRAFT→CREATED | ❌ (повторный клик шлёт повторное уведомление) | ❌ |
| `update_qty_*` | ❌ (можно менять количество у подтверждённого заказа через старое сообщение) | — |
| `confirm_order_*` CREATED→PROCESSING | ✅ | ✅ |
| `order_ready_*` PROCESSING→READY | ✅ | ✅ |
| `pickup_*` READY→CUSTOMER_NOTIFIED | ❌ (каждый клик шлёт новое сообщение в админ-чат) | ❌ |
| `order_complit_*` →RECEIVED | ❌ (можно «выдать» отклонённый заказ) | ❌ |
| `decline_order_*` →DECLINED | чёрный список `[2,5,6,7,8,9]`, то есть READY(4) отменить можно, а CUSTOMER_NOTIFIED(2) нельзя | — |

- ID статусов не соответствуют порядку процесса: 1 → 3 → 4 → **2** → 5. Константы `ORDER_STATUS_*` скопированы в 8 файлах, где-то `PAYED = 5`, где-то `RECEIVED = 5`, а в `PaymentConversationHandler` `PAYED = 2`.
- **Предложение:** `enum OrderStatus` и один сервис `orders.transition(order, to, actor)` с таблицей разрешённых переходов, где одновременно проверяются права и пишется лог. Хендлеры только вызывают сервис.

### 🔴 2.3 Деньги и объёмы
- `orders.total_price`, `product_sizes.price` имеют тип `NUMERIC(5,1)`, то есть максимум 9 999,9 ₽; `packages.price NUMERIC(4,1)` — 999,9 ₽; `sizes.name NUMERIC(2,1)` — 9,9 кг. Цены вводятся через `float()`. **Предложение:** `NUMERIC(10,2)`, `Decimal` при вводе, ограничить количество (например, 1–50).
- Остаток `products.quantity` существует, но нигде не уменьшается и не проверяется: продать можно больше, чем есть.
- `SIZES = ["0.5кг","1.0кг","1.5кг"]` жёстко прописан в `InsertProductConversation.py:56` и дублирует таблицу `sizes`.
- Тара привязана к размеру (`sizes.package_id`), выбрать её нельзя. Таблица `order_packages` не используется.

### 🟠 2.4 Черновики и сессии
- Каждый клик по размеру создаёт **новую** строку `sessions` (role 2) и **новый** черновик `orders` (`SelectProductConversation.py:189–232`). Истечение черновиков отключено (`main.py:75`), а сама джоба сломана (`DrinkSize`, `drink_size`).
- «Сессия» используется для трёх разных вещей: сессии покупки, записи на дегустацию (role 3 + `sent_message`) и входа менеджера (role 4 создаётся **при каждом** открытии меню). Таблица растёт без смысла.
- У дегустации нет сущности «мероприятие». Запись — это сессия с `role_id=3`, а рассылка помечает всех записавшихся `sent_message=True`. Получается, что запись действует ровно на одну ближайшую рассылку, и пользователю об этом не сообщают. Кто придёт, не фиксируется: «напишите „Приду“ в /help» уходит в свободный текст в админ-чат.
- **Предложение:** отдельная таблица `tasting_signups(user_id, event_id, status)` и таблица `tasting_events`. Черновик заказа держать в `user_data`, а в БД писать только при «Заказать». Если черновик в БД всё же нужен, нужны работающая джоба истечения и `UNIQUE(user_id) WHERE status = DRAFT`.

### 🟠 2.5 Статистика менеджера
`get_orders_products_statistics.py`:
- «Всего» считает **все** заказы, включая черновики, отклонённые и просроченные (`total_stmt` без фильтра по статусу).
- Блок «статус продажи В работе и Завершено» включает CREATED, то есть ещё не подтверждённые заказы.
- «Пользователей (записались)» — `count(Session.tg_user_id)` без `DISTINCT`.

### 🟠 2.6 Данные бизнеса разбросаны по коду
- Адрес пасеки «ул. Плотинная, д. 4» встречается в 4 местах, а в приглашении на дегустацию указано **«ул. Плотинная 2»** (`InvitationConversation.py:85`). Это фактическая ошибка в рассылке.
- Координаты, тексты приветствия, путь к фото и часовой пояс `timedelta(hours=3)` (6 мест) захардкожены. Сервер работает в Екатеринбурге (UTC+5), а `datetime.now()` в `OrderStatusCustomerButton.py:61` берёт время контейнера (UTC). С 00:00 до 03:00 МСК «сегодня» оказывается вчерашним днём.
- **Предложение:** `config.py` (pydantic-settings) для адреса, координат, TZ, контактов и ID чатов. Тексты вынести в `texts.py`. Время хранить в `timestamptz`, отображать через `ZoneInfo("Europe/Moscow")`.

### 🟡 2.7 Прочее по процессу
- Уведомление о новом заказе уходит в `ADMIN_CHAT_ID`, а об отмене гостем — в личку автора товара (`DeclineCancelOrderConversation.py:137`). Каналы не согласованы.
- Если у заказа нет менеджера, `customer_button_handler` показывает клиенту `☎️: None` или падает на `order.manager.phone_number`.
- Функция «последний заказ при повторном визите», обещанная в README, не работает: `get_last_order` содержит опечатку `.joinload` и нигде не вызывается.
- Доставка по зонам (`order_delivery`, `delivery_zones`, `geocoding`, FastAPI) реализована только на уровне моделей и нигде не используется.

---

## 3. Код и реализация

### 🔴 3.1 Баги, воспроизводимые по коду
1. `RegistrationConversation.py:348` — после `route_after_login` нет `return`. Хендлер возвращает `None`, и диалог остаётся в `ASK_PHONE`, а состояние `MAIN_MENU` недостижимо.
2. `RegistrationConversation.py:223` — `if not tg_name == None` инвертировано: при заполненном имени бот просит ввести имя, при пустом падает на `None.strip()`.
3. `ManagerOrdersConversation.py:81` — `if not orders: … elif not orders:` — ветка архива недостижима. `:150` возвращает `END` вместо `VIEW_ORDERS`, поэтому пагинация не работает.
4. `ManagerProductsHandler.py:17` ожидает `^honey_get_\d+$`, а кнопка «Вернуться назад» шлёт `honey_get`.
5. `ManagerProductsConversation.py:115` — при `productsize is None` код обращается к `productsize.product.name` и получает `AttributeError`. В том же файле строки 350–455 содержат копию рассылки, которая ссылается на неопределённые `ASK_DATE/ASK_TIME`.
6. `DeclineCancelOrderConversation.py:108` — `print(order.id)` стоит до проверки `if not order`.
7. `SelectProductConversation.py:517` — `session.commit()` без `await`. Сообщение `user_id=ADMIN_CHAT_ID` в логе ошибки тоже неверно.
8. `OrderStatusCustomerButton.py:95` — `lag` считается **после** обновления `updated_at` и всегда равен 0. Та же проблема отмечена комментарием в `OrderStatusConfirmed.py:87`.
9. `SelectProductConversation.py:423` — `last_order_message_id` нигде не устанавливается. Комментарий всегда создаёт новую карточку заказа, а старая остаётся с активными кнопками.
10. `UserSendProblemConversation.py:38` — `parse_mode="Markdown"` без экранирования. Если в имени или тексте есть `_`, `*`, `[` или `` ` ``, Telegram отвечает `BadRequest`, и жалоба пропадает. Там же `raise ApplicationHandlerStop` без `state` оставляет пользователя в `SEND_PROBLEM` навсегда.
11. `show_customer_menu` использует `update.message.reply_photo`. При вызове из колбэка (`back_menu`) `update.message is None`, и обработчик ошибки тоже падает.
12. Модели: `Order.__repr__` обращается к `self.drinks`, `Session.__repr__` к `self.location`, а `CheckConstraint("drink_count > 0")` ссылается на несуществующую колонку (при `create_all` будет ошибка, у `product_count` проверки нет).

### 🔴 3.2 Инъекция HTML / Markdown
Пользовательские строки подставляются в `parse_mode="HTML"` без `safe_html`: комментарий клиента, имя из профиля TG, название и описание товара от менеджера. Затронуты `SelectProductConversation.py:478–485`, `OrderStatusConfirmed.py:117`, `manager_lk_collection.py:46`, `full_view_manager.py:17`. Символ `<` в комментарии роняет уведомление менеджеру, и заказ теряется. `safe_html` при этом применяется там, где `parse_mode` не указан (`DeclineCancelOrderConversation.py:89`), и клиент видит `&lt;`.

Длина комментария не ограничена, а колонка `VARCHAR(255)`: длинный текст приводит к `DataError`, который ничем не обрабатывается.

### 🟠 3.3 Архитектура
- **Слоёв нет.** Хендлеры сами пишут SQL, собирают тексты, клавиатуры и шлют уведомления. Одинаковый `select(Order).options(selectinload…)` повторяется 8 раз, текст карточки заказа — 6 раз с расхождениями.
- **Паттерн `XxxHandler.py` + `XxxConversation.py` с `import *`** — 12 пар файлов, где «Handler» содержит 10–20 строк. Имена, экспортированные через `*` (`cancel`, `end_and_go`, `ADMIN_CHAT_ID`), затеняют друг друга.
- **Конфигурация при импорте.** `os.getenv` + `raise` на уровне модуля в 10 файлах. `ADMIN_CHAT_ID` в одних местах `str`, в других `int(...)`, и при отсутствии переменной вызов `int(None)` падает.
- **Мёртвый код** — около 25 % кодовой базы: `BookingChatConversation`, `PaymentConversationHandler` (импортирует `Drink`, `DrinkAdd` и требует `UKASSA_TOKEN`), `DegustationConversationHandler`, `check_expired_orders`, `api/*`, `schemas/*`, 9 утилит от проекта аренды (`apts_search_session`, `booking_*`, `delete_apartment`, `owner_*`, `renter_*`, `short_view`), `build_calendar`, `build_price_filter_keyboard`, `send_and_pin_message`, `sanitize_message`, модели доставки. Сюда же относятся закомментированные импорты в `main.py`.
- **Две `Base`**: `db/db.py:21` и `db/db_async.py:45`, в `db/__init__.py` вторая перезаписывает первую.
- **ORM-объекты в `user_data`** (`seller_orders`) — отсоединённые и устаревающие данные. Персистентности нет, и после рестарта все диалоги сбрасываются молча.
- **Нет `app.add_error_handler`.** Непойманные исключения уходят в stderr через `logging.lastResort`.
- **`preprocess_photo_crop_center`** обрабатывает фото через PIL синхронно в event loop и отправляет обработанное фото в чат менеджера, чтобы получить `file_id`. Менеджер видит лишние сообщения.
- В `route_after_login` сессия менеджера создаётся на каждый вход в меню, `get_manager_stats_message` выполняет 6 запросов подряд.

### 🟠 3.4 Работа с БД
- `ondelete="CASCADE"` на `orders.status_id`, `orders.product_size_id`, `orders.tg_user_id`: удаление статуса, размера или пользователя удаляет **историю заказов** (деньги). Нужно `RESTRICT`.
- `datetime.utcnow` (deprecated с 3.12) и naive `DateTime` вместо `timestamptz`.
- Транзакции не согласованы: в одних хендлерах `flush` → отправка сообщений → `commit`, и при ошибке Telegram заказ откатывается после того, как клиент уже получил «подтверждено». В других `commit` идёт первым.
- Нет индексов под частые запросы: `orders(status_id)`, `orders(tg_user_id)`, `products(type_id, is_active, is_draft)`, `sessions(role_id, sent_message)`.
- `serial_actualization.py` лежит в `db/tools`, хотя ему место в миграции или в `Makefile`.

### 🟡 3.5 Стиль
- 33 `print(...)`, включая `print(f"DEBUG-initial-user: {tg_user}")` с персональными данными.
- 45 `except Exception`, большинство показывают пользователю «❌ Ошибка: не найден ID заказа» независимо от реальной причины.
- Смесь терминов: «бронирование», «апартаменты», «напиток» в текстах для пользователя (`«❌ Бронирование не найдено.»`) и в логах (`action="apartment_price_updated"`).
- Файлы `CamelCase.py`, опечатки в именах (`Complit`, `Replay` вместо `Reply`).

---

## 4. Логирование

### 🔴 4.1 Логирование бота не инициализировано
- `setup_logging()` вызывается только в `api/main.py` (FastAPI не запускается). Бот использует объект `structured_logger`, созданный при импорте с настройками по умолчанию.
- Стандартный `logging` не настроен (`basicConfig` нет). Логи PTB, httpx и SQLAlchemy и необработанные исключения не попадают в файл и лог-вьюер.
- `create_async_engine(echo=True)` выводит в stdout **каждый** SQL-запрос вместе с параметрами: телефонами, именами, комментариями.

### 🟠 4.2 Самописный `StructuredLogger` обходит `logging`
- `log()` сам открывает файл через `open(..., 'a')` на **каждую** запись. Это синхронный I/O в event loop, без блокировки, без ротации и без учёта уровня: `LOG_LEVEL` из `.env` не влияет, в файл пишется DEBUG.
- Внутренний `logging.Logger("bot_logger")` с `FileHandler` создаётся, но не используется для записи. `setup_logging` добавляет ему консольный хендлер, в который никто не пишет.
- `json.dumps` без `ensure_ascii=False`, поэтому кириллица в файле хранится как `\uXXXX`. `datetime.utcnow()`.
- `_get_caller_info(skip_frames=3)` при вызове через `.info()` указывает не на того вызывающего: в логе оказывается `log_database_operation`/`__exit__`, а не хендлер.
- Модуль импортирует `fastapi` и `starlette`, то есть бот зависит от веб-фреймворка ради логгера. Две копии HTTP-middleware не используются.

### 🟠 4.3 Декораторы и контексты
- `log_db_select(slow_threshold=0.5)` при `log_success=True` пишет каждую удачную операцию **с уровнем WARNING**, если она медленнее порога, иначе ничего. Для insert/update, где `min_execution_time=0`, условие `execution_time >= 0` всегда истинно, и каждая успешная вставка логируется как **WARNING**.
- `log_db_update` висит на хендлерах PTB (`ProductConfirmHandler.py:14`), а не на DB-функциях. `user_id` извлекается через `getattr(args[0], 'user_id')` у `Update` и всегда равен `None`.
- `LoggingContext` на каждый шаг пишет пару DEBUG+INFO. Внутри него хендлеры ловят исключения сами, поэтому ветка ошибки контекста не срабатывает никогда.
- `check_expired_orders.py`, `delete_apartment.py`, `PaymentConversationHandler.py` импортируют `log_function_call`, `LogExecutionTime`, `get_logger`, которых в модуле нет. Импорт любого из них падает.

### 🟠 4.4 Содержимое логов
- Персональные данные: `username`, `first_name`, `original_input`, `sanitized_name`, **полный текст комментария** (`comment=comment_text`), `tg_user` целиком в `print`.
- Нет `update_id`/correlation id, по которому можно связать записи одного апдейта.
- `action` — свободная строка в разных стилях: `"Order accepted"`, `"order complit"`, `"apartment_upgrade_start"`, `"Create order draft"`. Фильтровать по ней во вьюере неудобно.
- `db_monitor.check_db` **каждые 30 минут** шлёт в чат «база доступна», а ошибку проглатывает (`except: pass`) без записи в лог. Получается шум при отсутствии сигнала.

### 🟠 4.5 Лог-вьюер
- Работает без авторизации на `0.0.0.0:${LOG_VIEWER_PORT}` при наличии персональных данных (см. §1.3).
- `read_structured_logs` делает `readlines()` всего файла на каждый запрос, а `/api/stats` читает до 10 000 записей. Без ротации файла память и время ответа растут линейно.

### Предложение по логированию
1. Один модуль `logging_setup.py`: `logging.config.dictConfig` с JSON-форматтером (`python-json-logger` или `structlog`), `RotatingFileHandler`/`TimedRotatingFileHandler` и stdout. Уровень берётся из `LOG_LEVEL`.
2. Логгеры модулей через `logging.getLogger(__name__)`. Контекст (`user_id`, `chat_id`, `update_id`, `order_id`) передаётся через `contextvars` в фильтре, который выставляет middleware, то есть `TypeHandler(Update)` в группе `-1`.
3. `app.add_error_handler(on_error)`: логирование с трейсбеком и короткое сообщение в админ-чат (с троттлингом).
4. `echo=False`. Для медленных запросов использовать события SQLAlchemy `before/after_cursor_execute` с порогом.
5. Персональные данные маскировать фильтром: телефон `+7***1234`, комментарий логировать только по длине.
6. Список `action` сделать `Enum`: `order.created`, `order.confirmed`, `product.published`…
7. Мониторинг БД: сообщение только при **смене** состояния и heartbeat-файл для healthcheck. Лог-вьюер закрыть авторизацией или заменить на Loki+Grafana / Dozzle.

---

## 5. План рефакторинга

### Этап 0 — срочные исправления (1–2 дня, без изменения архитектуры)
- [ ] Проверка роли на `honey_add`, `confirm_product_*`, `redo_product_*` и остальных менеджерских колбэках.
- [ ] Миграция: `NUMERIC(10,2)` для цен и сумм, лимит количества.
- [ ] `return` после регистрации, инвертированное условие имени, `fallbacks` в отклонении, `VIEW_ORDERS` в заказах, `honey_get`.
- [ ] `safe_html` для всех пользовательских строк в HTML, лимит длины комментария.
- [ ] Идемпотентность `pay_*`, `pickup_*`, `order_complit_*` через проверку статуса.
- [ ] Адрес дегустации «Плотинная 2» → «4».
- [ ] `echo=False`, вызов `setup_logging()` в `main.py`, `add_error_handler`.
- [ ] Закрыть порты Postgres и лог-вьюера, исправить `.dockerignore`, убрать `./bot:/bot`.
- [ ] Закоммитить `db/init` и справочники.

### Этап 1 — каркас (≈1 неделя)
- [ ] Удалить мёртвый код (≈25 %).
- [ ] `config.py` на pydantic-settings, без `os.getenv` в модулях.
- [ ] `pyproject.toml`, `ruff`, `pytest`, GitHub Actions.
- [ ] Новый модуль логирования (§4) и удаление `StructuredLogger` с декораторами.
- [ ] Alembic на async, одна `Base`, удаление `db/db.py`.

### Этап 2 — домен (≈1–2 недели)
- [ ] `enum OrderStatus`/`Role`, сервис переходов заказа с таблицей разрешённых переходов.
- [ ] Роль в `users.role_id`, декоратор `@require_role`.
- [ ] Репозитории и сервисы (`services/orders.py`, `services/catalog.py`, `services/notifications.py`), в хендлерах только UI.
- [ ] Отдельные `tasting_events` и `tasting_signups`, `sessions` убрать или свести к аудиту.
- [ ] Черновик заказа в `user_data` либо джоба истечения.
- [ ] `timestamptz` и `ZoneInfo`, `ondelete=RESTRICT` для заказов.
- [ ] Тесты на сервисы: переходы статусов, расчёт суммы, статистика.

### Этап 3 — эксплуатация
- [ ] `PicklePersistence` или персистентность в Postgres для диалогов.
- [ ] Бэкапы `pg_dump` по крону на RAID и проверка восстановления.
- [ ] Healthcheck бота и алерт при смене состояния.
- [ ] Обновление PTB до 21.x/22.x.

### Целевая структура
```
bot/
  app/
    main.py              # сборка Application, регистрация роутеров
    config.py            # pydantic-settings
    logging_setup.py
    texts.py             # все пользовательские тексты
    domain/
      enums.py           # OrderStatus, Role
      order_flow.py      # разрешённые переходы
    db/
      base.py  session.py  models/  repositories/
    services/
      orders.py  catalog.py  tasting.py  stats.py  notifications.py
    bot/
      middlewares.py     # контекст логов, загрузка user, проверка роли
      keyboards.py
      handlers/
        customer/  registration.py  catalog.py  order.py
        manager/   products.py  orders.py  tasting.py
        common/    help.py  info.py  errors.py
  migrations/
  tests/
```
