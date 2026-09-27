
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from handlers.RegistrationConversation import (
    ASK_PHONE,
    MAIN_MENU,
    NAME_REQUEST,
    cancel,
    handle_name_request,
    handle_phone_registration,
    handle_show_map,
    route_after_login,
    start,
)

registration_conversation = ConversationHandler(
    # состояние диалога сохраняется в PicklePersistence и переживает перезапуск бота
    name="registration",
    persistent=True,
    entry_points=[
        CommandHandler("start", start)
    ],
    states={
        NAME_REQUEST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_request)
        ],
        ASK_PHONE: [MessageHandler(filters.TEXT | filters.CONTACT, handle_phone_registration)],
        MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND,route_after_login),
                    CallbackQueryHandler(handle_show_map, pattern="^show_map$")
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel)
    ],
    conversation_timeout=300
)
