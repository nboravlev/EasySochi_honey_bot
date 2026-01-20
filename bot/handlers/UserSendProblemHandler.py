from handlers.UserSendProblemConversation import *

problem_handler = ConversationHandler(
    entry_points=[CommandHandler("help", start_problem)],
    states={
        SEND_PROBLEM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_problem)
        ]
    },
    fallbacks=[CommandHandler("cancel",cancel_command)],
    per_user=True,  # Важно! Состояние ведётся раздельно для чатов
)