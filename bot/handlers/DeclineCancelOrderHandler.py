from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from handlers.DeclineCancelOrderConversation import (
    DECLINE_REASON,
    booking_decline_callback,
    booking_decline_reason,
    cancel_decline,
)

conv_decline_cancel = ConversationHandler(
    # состояние диалога сохраняется в PicklePersistence и переживает перезапуск бота
    name="decline_order",
    persistent=True,
    entry_points=[CallbackQueryHandler(booking_decline_callback, pattern=r"^decline_order_\d+$")],
    states={
        DECLINE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_decline_reason)]
    },
    fallbacks=[CommandHandler("cancel", cancel_decline)],
    conversation_timeout=300
)