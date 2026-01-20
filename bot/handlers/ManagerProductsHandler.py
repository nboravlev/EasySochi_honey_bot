from handlers.ManagerProductsConversation import *

manager_products = ConversationHandler(
    entry_points=[
                  CallbackQueryHandler(handle_manager_products, pattern="^honey_get$")
],
    states={

            VIEW_PRODUCTS: [CallbackQueryHandler(handle_manager_products, pattern="^honey_get$"),
                            CallbackQueryHandler(handle_product_upgrade, pattern=r"^edit_sizeprice_\d+$"),
                        CallbackQueryHandler(confirm_delete_product, pattern=r"^product_delete_\d+$"),
                        CallbackQueryHandler(delete_product_confirmed, pattern=r"^delete_confirm_\d+$"),
                        CallbackQueryHandler(cancel_delete_product, pattern=r"^delete_cancel$")
            ],
            EDIT_PRICE_PROMPT: [
                    CallbackQueryHandler(handle_edit_price_start, pattern="^edit_price_start$"),
                    CallbackQueryHandler(handle_manager_products, pattern=r"^honey_get_\d+$")
                ],
            EDIT_PRICE_WAIT_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_price_input)
                ],
    },
    fallbacks=[
        CommandHandler("cancel", end_and_go)
    ]

)