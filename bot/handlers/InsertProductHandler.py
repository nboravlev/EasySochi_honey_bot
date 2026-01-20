from handlers.InsertProductConversation import *

insert_product_conv = ConversationHandler(
    entry_points=[
        CommandHandler("honey_add", start_add_object),
        CallbackQueryHandler(start_add_object, pattern="^honey_add$")
    ],
    states={
        PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_object_name)],
        PRODUCT_TYPE: [CallbackQueryHandler(handle_object_type, pattern=r'^\d+$')],
        PRODUCT_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_object_size)], 
        PRODUCT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)],
        PRODUCT_PHOTO: [
            MessageHandler(filters.PHOTO, handle_photo),
            MessageHandler(filters.Regex("^(Готово|готово)$"), handle_photos_done)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel, pattern="cancel")
    ],
    allow_reentry=True,
    conversation_timeout=300
)



