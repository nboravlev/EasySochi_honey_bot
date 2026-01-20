from handlers.SelectProductConversation import *

select_product_conv = ConversationHandler(
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
)


