from telegram.ext import CommandHandler, ConversationHandler, MessageHandler, filters

from handlers.UserSendProblemConversation import (
    SEND_PROBLEM,
    cancel_command,
    process_problem,
    start_problem,
)

problem_handler = ConversationHandler(
    # состояние диалога сохраняется в PicklePersistence и переживает перезапуск бота
    name="user_problem",
    persistent=True,
    entry_points=[CommandHandler("help", start_problem)],
    states={
        SEND_PROBLEM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_problem)
        ]
    },
    fallbacks=[CommandHandler("cancel",cancel_command)],
    per_user=True,  # Важно! Состояние ведётся раздельно для чатов
    conversation_timeout=900,
)