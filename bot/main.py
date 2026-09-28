import os
from pathlib import Path

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    BasePersistence,
    DictPersistence,
    PicklePersistence,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    TypeHandler,
)
from telegram.request import BaseRequest

from config import get_settings
from db_monitor import DB_CHECK_INTERVAL_SEC, HEARTBEAT_INTERVAL_SEC, check_db, write_heartbeat
from handlers.AdminReplayUserProblemHandler import admin_replay_handler
from handlers.DeclineCancelOrderHandler import conv_decline_cancel
from handlers.InsertProductHandler import insert_product_conv
from handlers.InvitationHandler import invitation
from handlers.ManagerOrdersHandler import manager_orders
from handlers.ManagerProductsHandler import manager_products
from handlers.InvitationConversation import tasting_rsvp
from handlers.ManagersAdmin import managers_handlers
from handlers.OrderStatusFlow import (
    customer_button_handler,
    order_complit_handler,
    order_confirmation,
    order_ready_handler,
)
from handlers.ProductConfirmHandler import confirm_handler
from handlers.ProductRedoHandler import redo_handler
from handlers.RegistrationConversation import handle_honey_try, handle_show_map, route_after_login
from handlers.RegistrationHandler import registration_conversation
from handlers.SelectProductHandler import select_product_conv
from handlers.ShowInfoHandler import info_callback_handler, info_command
from handlers.UserSendProblemHandler import problem_handler
from db.db_async import get_async_session
from services.orders import expire_stale_drafts
from services.shops import bootstrap_storefront, storefront_shop_id
from services.users import bootstrap_managers
from utils.logging_config import bind_update_context, setup_logging, structured_logger
from utils.telegram_delivery import DISPATCH_INTERVAL_SEC, dispatch_due_job, purge_job

USER_COMMANDS = [
    BotCommand("start", "🔄 Перезапустить бот"),
    BotCommand("help", "⚠️ Помощь"),
    BotCommand("info", "📌 Инструкция"),
    BotCommand("cancel", "⛔ Отмена"),
]
OWNER_COMMANDS = USER_COMMANDS + [
    BotCommand("managers", "👥 Менеджеры"),
    BotCommand("manager_add", "➕ Назначить менеджера"),
]


async def bind_log_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Группа -1: контекст апдейта для всех записей лога, сделанных при его обработке."""
    bind_update_context(
        update_id=update.update_id,
        telegram_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Все необработанные исключения хендлеров и джоб — в лог, а не в пустоту stderr."""
    update_kind = type(update).__name__ if update is not None else None
    if isinstance(update, Update):
        if update.callback_query:
            update_kind = f"callback:{update.callback_query.data}"
        elif update.message and update.message.text and update.message.text.startswith("/"):
            update_kind = f"command:{update.message.text.split()[0]}"
    structured_logger.error(
        f"Unhandled error: {context.error!r}",
        action="unhandled_error",
        exception=context.error,
        context={"update": update_kind},
    )


async def expire_drafts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Раз в час закрывает брошенные черновики заказов (покупателю ничего не пишем)."""
    async with get_async_session() as session:
        expired = await expire_stale_drafts(session)
        await session.commit()
    if expired:
        structured_logger.info("Stale drafts expired", action="drafts_expired", context={"count": expired})


async def post_init(application: Application) -> None:
    settings = get_settings()

    # первый запуск после миграций: служебный чат и телефон витрины — из ADMIN_CHAT_ID / SELLER_CONTACT,
    # MANAGER_LIST — менеджеры витрины. Дальше всё хранится в БД (shop_channels, users.role_id/shop_id).
    async with get_async_session() as session:
        filled = await bootstrap_storefront(session, settings.admin_chat_id, settings.seller_contact)
        storefront_id = await storefront_shop_id(session)
        promoted = await bootstrap_managers(session, settings.manager_ids - {settings.owner_id}, storefront_id)
        await session.commit()
    if filled or promoted:
        structured_logger.info("Storefront bootstrapped from .env", action="storefront_bootstrap",
                               context={"filled": filled, "managers": promoted})

    # Настройка меню команд (синяя плашка); владельцу — ещё и управление менеджерами
    await application.bot.set_my_commands(USER_COMMANDS)
    if settings.owner_id:
        try:
            await application.bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(settings.owner_id))
        except Exception as exc:  # владелец ещё не писал боту
            structured_logger.warning("Owner commands not set", action="owner_commands_failed",
                                      context={"error": str(exc)})

    schedule_jobs(application)


def schedule_jobs(application: Application) -> None:
    jobs = application.job_queue
    jobs.run_repeating(write_heartbeat, interval=HEARTBEAT_INTERVAL_SEC, first=0)
    jobs.run_repeating(check_db, interval=DB_CHECK_INTERVAL_SEC, first=10)
    jobs.run_repeating(expire_drafts_job, interval=60 * 60, first=60)
    # уведомления, не ушедшие сразу (Telegram не ответил), и чистка старых строк очереди
    jobs.run_repeating(dispatch_due_job, interval=DISPATCH_INTERVAL_SEC, first=15)
    jobs.run_repeating(purge_job, interval=24 * 60 * 60, first=5 * 60)


def build_persistence() -> BasePersistence:
    """Файл состояния на томе; если каталог недоступен — в памяти (бот работает, но диалоги не переживут рестарт)."""
    state_file = get_settings().state_file
    if state_file:
        path = Path(state_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not os.access(path.parent, os.W_OK):
                raise PermissionError(f"{path.parent} is not writable")
            # пустой файл PTB не распакует и упадёт при старте — считаем, что состояния нет
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
            return PicklePersistence(filepath=path)
        except OSError as exc:
            structured_logger.warning(
                "State file is not writable, conversations won't survive restart",
                action="persistence_unavailable", context={"state_file": state_file, "error": str(exc)},
            )
    return DictPersistence()


def build_application(
    persistence: BasePersistence | None = None, request: BaseRequest | None = None
) -> Application:
    """request — подмена HTTP-клиента Telegram (сквозные тесты), в работе не передаётся."""
    settings = get_settings()

    builder = ApplicationBuilder().token(settings.bot_token).post_init(post_init)
    builder = builder.persistence(persistence or build_persistence())
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    else:
        # тайм-ауты увеличены: Telegram из РФ отвечает медленно и иначе возвращает ошибку
        builder = builder.connect_timeout(30).read_timeout(30).write_timeout(60)
    app = builder.build()

    app.add_error_handler(on_error)
    app.add_handler(TypeHandler(Update, bind_log_context), group=-1)

    # глобальные обработчики
    app.add_handler(CommandHandler("info", info_command), group=0)
    app.add_handler(CallbackQueryHandler(route_after_login, pattern="^back_menu$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_show_map, pattern=r"^show_map(_\d+)?$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_honey_try, pattern="^honey_try$"), group=0)
    app.add_handler(CallbackQueryHandler(order_confirmation, pattern=r"^confirm_order_\d+$"), group=0)
    app.add_handler(CallbackQueryHandler(order_ready_handler, pattern=r"^order_ready_\d+$"), group=0)
    app.add_handler(
        CallbackQueryHandler(customer_button_handler, pattern=r"^pickup_(today|tomorrow|later)_\d+$"), group=0
    )
    app.add_handler(CallbackQueryHandler(order_complit_handler, pattern=r"^order_complit_\d+$"), group=0)
    app.add_handler(CallbackQueryHandler(tasting_rsvp, pattern=r"^tasting_(yes|no)_\d+$"), group=0)
    for handler in managers_handlers:
        app.add_handler(handler, group=0)
    app.add_handler(problem_handler, group=0)
    app.add_handler(admin_replay_handler, group=0)

    # сценарии
    app.add_handler(CallbackQueryHandler(info_callback_handler, pattern=r"^info_"), group=1)
    app.add_handler(registration_conversation, group=1)  # регистрация (users, sessions), выбор роли
    app.add_handler(insert_product_conv, group=1)        # создание карточки товара
    app.add_handler(confirm_handler, group=1)            # публикация карточки товара
    app.add_handler(redo_handler, group=1)               # отмена карточки
    app.add_handler(select_product_conv, group=1)        # выбор мёда и оформление заказа
    app.add_handler(conv_decline_cancel, group=1)        # отклонение заказа
    app.add_handler(manager_orders, group=1)
    app.add_handler(manager_products, group=1)
    app.add_handler(invitation, group=1)
    return app


def main():
    settings = get_settings()
    setup_logging(log_dir=settings.log_dir, log_level=settings.log_level, enable_console=True)
    build_application().run_polling()


if __name__ == "__main__":
    main()
