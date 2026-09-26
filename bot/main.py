from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    TypeHandler,
)

from config import get_settings
from db_monitor import check_db
from handlers.AdminReplayUserProblemHandler import admin_replay_handler
from handlers.DeclineCancelOrderHandler import conv_decline_cancel
from handlers.InsertProductHandler import insert_product_conv
from handlers.InvitationHandler import invitation
from handlers.ManagerOrdersHandler import manager_orders
from handlers.ManagerProductsHandler import manager_products
from handlers.OrderStatusComplit import order_complit_handler
from handlers.OrderStatusConfirmed import order_confirmation
from handlers.OrderStatusCustomerButton import customer_button_handler
from handlers.OrderStatusReady import order_ready_handler
from handlers.ProductConfirmHandler import confirm_handler
from handlers.ProductRedoHandler import redo_handler
from handlers.RegistrationConversation import handle_honey_try, handle_show_map, route_after_login
from handlers.RegistrationHandler import registration_conversation
from handlers.SelectProductHandler import select_product_conv
from handlers.ShowInfoHandler import info_callback_handler, info_command
from handlers.UserSendProblemHandler import problem_handler
from utils.logging_config import bind_update_context, setup_logging, structured_logger


async def bind_log_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Группа -1: контекст апдейта для всех записей лога, сделанных при его обработке."""
    bind_update_context(
        update_id=update.update_id,
        user_id=update.effective_user.id if update.effective_user else None,
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


async def post_init(application: Application) -> None:
    # Настройка меню команд (синяя плашка)
    await application.bot.set_my_commands([
        BotCommand("start", "🔄 Перезапустить бот"),
        BotCommand("help", "⚠️ Помощь"),
        BotCommand("info", "📌 Инструкция"),
        BotCommand("cancel", "⛔ Отмена"),
    ])

    application.job_queue.run_repeating(check_db, interval=30 * 60, first=10)


def build_application() -> Application:
    settings = get_settings()

    # тайм-ауты увеличены: Telegram из РФ отвечает медленно и иначе возвращает ошибку
    app = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(60)
        .post_init(post_init)
        .build()
    )

    app.add_error_handler(on_error)
    app.add_handler(TypeHandler(Update, bind_log_context), group=-1)

    # глобальные обработчики
    app.add_handler(CommandHandler("info", info_command), group=0)
    app.add_handler(CallbackQueryHandler(route_after_login, pattern="^back_menu$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_show_map, pattern="^show_map$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_honey_try, pattern="^honey_try$"), group=0)
    app.add_handler(CallbackQueryHandler(order_confirmation, pattern=r"^confirm_order_\d+$"), group=0)
    app.add_handler(CallbackQueryHandler(order_ready_handler, pattern=r"^order_ready_\d+$"), group=0)
    app.add_handler(
        CallbackQueryHandler(customer_button_handler, pattern=r"^pickup_(today|tomorrow|later)_\d+$"), group=0
    )
    app.add_handler(CallbackQueryHandler(order_complit_handler, pattern=r"^order_complit_\d+$"), group=0)
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
