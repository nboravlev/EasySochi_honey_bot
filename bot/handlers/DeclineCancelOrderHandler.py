from handlers.DeclineCancelOrderConversation import *

conv_decline_cancel = ConversationHandler(
    entry_points=[CallbackQueryHandler(booking_decline_callback, pattern=r"^decline_order_\d+$")],
    states={
        DECLINE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_decline_reason)]
    },
    fallbacks=["cancel", cancel_decline],
    conversation_timeout=300
)