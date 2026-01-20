from handlers.RegistrationHandler import registration_conversation
from handlers.InsertProductHandler import insert_product_conv
from handlers.ProductConfirmHandler import confirm_handler
from handlers.ProductRedoHandler import redo_handler
from handlers.SelectProductHandler import select_product_conv
from handlers.DeclineCancelOrderHandler import conv_decline_cancel
#from handlers.BookingChatHandler import booking_chat
from handlers.UserSendProblemHandler import problem_handler
from handlers.AdminReplayUserProblemHandler import admin_replay_handler
#from handlers.UnknownComandHandler import unknown_command_handler
from handlers.GlobalCommands import cancel_command
from handlers.ShowInfoHandler import info_callback_handler, info_command
#from handlers.PaymentConversationHandler import PreCheckoutQueryHandler, pay_order, precheckout_handler, successful_payment_handler
#from handlers.GetOrderConversationHandler import order_received_handler
from handlers.RegistrationConversation import route_after_login,handle_honey_try,handle_show_map
from handlers.OrderStatusConfirmed import order_confirmation
from handlers.OrderStatusReady import order_ready_handler
from handlers.OrderStatusCustomerButton import customer_button_handler
from handlers.OrderStatusComplit import order_complit_handler
from handlers.ManagerOrdersHandler import manager_orders
from handlers.ManagerProductsHandler import manager_products
from handlers.InvitationHandler import invitation
from db_monitor import check_db
#from check_expired_orders import check_expired_order

import os
from pathlib import Path
from datetime import time


#from utils.call_coffe_size import init_size_map

import os

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    BotCommand,
    BotCommandScopeChat
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ApplicationBuilder,
    JobQueue
)
# Initialize comprehensive logging


async def post_init(application: Application) -> None:
    # Настройка меню команд (синяя плашка)
    commands = [
        BotCommand("start", "🔄 Перезапустить бот"),
        BotCommand("help", "⚠️ Помощь"),
        BotCommand('info', "📌 Инструкция"),
        BotCommand("cancel", "⛔ Отмена")

    ]
    await application.bot.set_my_commands(commands)

    # Инициализация SIZE_MAP
    #await init_size_map()



    application.job_queue.run_repeating(
        check_db,
        interval=30 * 60,
        first=10
    )
    #application.job_queue.run_repeating(
    #check_expired_order,
    #interval=30 * 60,
    #first=6
    #)


def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in .env")


    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    #глобальные обработчики
    app.add_handler(CommandHandler("info",info_command), group=0)
    app.add_handler(CallbackQueryHandler(route_after_login, pattern="^back_menu$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_show_map, pattern="^show_map$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_honey_try, pattern="^honey_try$"), group=0)
    app.add_handler(CallbackQueryHandler(order_confirmation, pattern = r"^confirm_order_\d+$"),group=0)
    app.add_handler(CallbackQueryHandler(order_ready_handler, pattern = r"^order_ready_\d+$"),group=0)
    app.add_handler(CallbackQueryHandler(customer_button_handler, pattern = r"^pickup_(today|tomorrow|later)_\d+$"),group=0)
    app.add_handler(CallbackQueryHandler(order_complit_handler, pattern = r"^order_complit_\d+$"),group=0)
    app.add_handler(problem_handler, group=0)
    app.add_handler(admin_replay_handler,group=0)

    #app.add_handler(CallbackQueryHandler(lambda u,c: print("CAUGHT:", u.callback_query.data)), group=0) - обработка пролетающих мимо коллбэков

    #админские обработки
    app.add_handler(CallbackQueryHandler(info_callback_handler, pattern=r"^info_"),group=1)
    #app.add_handler(unknown_command_handler,group=0) #обработчик незнакомых команд
    
    # Регистрируем хендлеры
    
    app.add_handler(registration_conversation, group=1) #процесс регистрации (users, sessions), выбор роли
    app.add_handler(insert_product_conv, group=1)  #создание карточки товара
    app.add_handler(confirm_handler, group=1) #сохранение карточки товара
    app.add_handler(redo_handler, group=1)  #отмена карточки
    app.add_handler(select_product_conv, group=1)  #показ карточек кофе
    app.add_handler(conv_decline_cancel, group=1) #отказ-подтверждение заказа
    app.add_handler(manager_orders, group=1)
    app.add_handler(manager_products, group=1)
    app.add_handler(invitation, group=1)
    #app.add_handler(CallbackQueryHandler(pay_order, pattern=r"^pay_"),group=1)
    #app.add_handler(PreCheckoutQueryHandler(precheckout_handler),group=1)
   
    #app.add_handler(CallbackQueryHandler(order_received_handler, pattern=r"^order_received_\d+"),group=1)  #обработка нажатия гостем кнопки получения заказа


    # Без asyncio
    app.run_polling()

if __name__ == "__main__":

    main()
