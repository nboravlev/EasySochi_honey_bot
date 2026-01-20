from handlers.InvitationConversation import *

invitation = ConversationHandler(
    entry_points=[CallbackQueryHandler(honey_invite_start, pattern="^honey_invite$")],
    states={
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, honey_invite_ask_date)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, honey_invite_ask_time)],
    },
    fallbacks=[
        CommandHandler("cancel", end_and_go)
    ],
    conversation_timeout=300,  # 5 minutes timeout
    per_user=True,
    per_chat=True

)