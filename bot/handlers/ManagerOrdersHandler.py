from handlers.ManagerOrdersConversation import *

manager_orders = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_seller_orders, pattern=r"^honey_orders_\d+$")],
    states={
            VIEW_ORDERS: [CallbackQueryHandler(handle_seller_orders, pattern=r"^owner_order_(next|prev|filter)_(\d+|all)$"),
                          ],

    },
    fallbacks=[
        CommandHandler("cancel", end_and_go)
    ]

)