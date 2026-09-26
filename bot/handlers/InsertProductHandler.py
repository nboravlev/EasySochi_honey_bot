from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from handlers.InsertProductConversation import (
    PRODUCT_DESCRIPTION,
    PRODUCT_NAME,
    PRODUCT_PHOTO,
    PRODUCT_SIZE,
    PRODUCT_TYPE,
    cancel,
    handle_description,
    handle_object_name,
    handle_object_size,
    handle_object_type,
    handle_photo,
    handle_photos_done,
    start_add_object,
)

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



