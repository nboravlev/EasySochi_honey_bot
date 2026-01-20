from db.db_async import get_async_session
from db.models.products import Product
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from sqlalchemy import select
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from utils.message_tricks import add_message_to_cleanup, send_message
from utils.logging_config import log_db_update, structured_logger, LoggingContext


@log_db_update
async def confirm_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message


    try:
        product_id = int(query.data.split("_")[-1])
        
        async with get_async_session() as session:
            result = await session.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            print(f"DEBUG_COMMIT: {product.name}")

            product.is_draft = False
            structured_logger.info(
                "New product",
                product_name=product.name,
                action="New product created",
                context={'tg_id': product.created_by}
            )
            await session.commit()

            
        confirmation_text = "🏆 Карточка товара сохранена. Желаю хороших продаж!"

        keyboard = [[
        InlineKeyboardButton("✍🏻 Создать ещё карточку", callback_data="honey_add"),
        InlineKeyboardButton("В главное меню ➡️", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправка / редактирование сообщения
        if message.text:

             await query.edit_message_text(confirmation_text, reply_markup=reply_markup)
        elif message.caption:

             await query.edit_message_caption(caption=confirmation_text, reply_markup=reply_markup)
        else:

             await message.reply_text(confirmation_text, reply_markup=reply_markup)


    except Exception as e:
        # LoggingContext will automatically log the error with full context
        structured_logger.error(
            f"Critical error in product confirmation: {str(e)}",
            user_id = update.effective_user.id,
            action="confirm_product_error",
            exception=e,
            context={
                'error_type': type(e).__name__
            }
        )
        print(e)
        await send_message(update, text = "не удалось сохранение. Попробуйте позже или обратитесь в поддержку."
        )
        return ConversationHandler.END


confirm_handler = CallbackQueryHandler(

    confirm_product_callback,
    pattern=r"^confirm_product_\d+$"
)
