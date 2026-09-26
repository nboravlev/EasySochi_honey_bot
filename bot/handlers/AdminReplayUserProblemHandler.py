from telegram.ext import CallbackQueryHandler, ConversationHandler, MessageHandler, filters

from handlers.AdminReplayUserProblemConversation import (
    REPLY_WAITING,
    handle_admin_reply,
    reply_callback,
)

admin_replay_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(reply_callback, pattern="^reply_")],
    states={
        REPLY_WAITING: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_reply)
        ]
    },
    fallbacks=[],
    per_chat=True,  # Важно! Состояние ведётся раздельно для чатов
)