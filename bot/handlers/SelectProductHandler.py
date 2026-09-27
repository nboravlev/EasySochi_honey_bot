from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from handlers.SelectProductConversation import (
    CUSTOMER_COMMENT,
    PRODUCT_TYPES_SELECTION,
    SELECT_QUANTITY,
    SELECT_SIZE,
    cancel,
    customer_comment_handler,
    handle_product_type_selection,
    handle_size_selection,
    handle_update_quantity,
    proceed_new_order,
    save_customer_comment,
    start_select_product,
)

select_product_conv = ConversationHandler(
    # состояние диалога сохраняется в PicklePersistence и переживает перезапуск бота
    name="select_product",
    persistent=True,
    entry_points=[CallbackQueryHandler(start_select_product, pattern="^honey_buy$"),
                  CommandHandler("honey_buy", start_select_product),
                  CallbackQueryHandler(handle_size_selection, pattern=r"^select_size_\d+$")],
    states={
        PRODUCT_TYPES_SELECTION: [CallbackQueryHandler(handle_product_type_selection, pattern=r"^product_type_\d+$")],
        SELECT_SIZE: [CallbackQueryHandler(handle_size_selection, pattern=r"^select_size_\d+$"),
                      CallbackQueryHandler(handle_update_quantity, pattern="^update_qty_"),
                      CallbackQueryHandler(customer_comment_handler, pattern=r"^customer_comment_\d+$"),
                      CallbackQueryHandler(start_select_product, pattern="^honey_buy$"),
                      CallbackQueryHandler(proceed_new_order, pattern=r"^pay_\d+$")],
        SELECT_QUANTITY: [CallbackQueryHandler(handle_update_quantity, pattern="^update_qty_"),
                        CallbackQueryHandler(customer_comment_handler, pattern=r"^customer_comment_\d+$"),
                        CallbackQueryHandler(start_select_product, pattern="^honey_buy$"),
                       CallbackQueryHandler(proceed_new_order, pattern=r"^pay_\d+$")   
            ],
        CUSTOMER_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_customer_comment)]
                },
    fallbacks=[CommandHandler("cancel", cancel)],
    # без таймаута пользователь, не дописавший комментарий, оставался в CUSTOMER_COMMENT навсегда
    allow_reentry=True,
    conversation_timeout=1800,
)


