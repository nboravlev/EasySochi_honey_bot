# Fixed ConversationHandler configuration

from handlers.RegistrationConversation import *

registration_conversation = ConversationHandler(
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
