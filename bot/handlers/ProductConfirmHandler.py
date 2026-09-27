from db.db_async import get_async_session
from db.models.products import Product
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from sqlalchemy import select
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from utils.message_tricks import send_message
from utils.logging_config import structured_logger
from utils.access import manager_only, is_owner


@manager_only
async def confirm_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message
    tg_user_id = update.effective_user.id


    try:
        product_id = int(query.data.split("_")[-1])

        async with get_async_session() as session:
            result = await session.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()

            # публикует только автор черновика (или владелец); удалённую карточку не воскрешаем
            if (product is None or not product.is_active
                    or (product.created_by != tg_user_id and not is_owner(tg_user_id))):
                await query.answer("Карточка не найдена или недоступна.", show_alert=True)
                return ConversationHandler.END
            await query.answer()

            product.is_draft = False
            structured_logger.info(
                "New product",
                user_id=tg_user_id,
                product_name=product.name,
                action="product_published",
                context={'tg_id': product.created_by, 'product_id': product.id}
            )
            await session.commit()

            
        confirmation_text = "🏆 Карточка товара сохранена. Желаю хороших продаж!"

        keyboard = [[
        InlineKeyboardButton("✍🏻 Создать ещё карточку", callback_data="honey_add"),
        InlineKeyboardButton("В главное меню ➡️", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправка / редактирование сообщения
        if getattr(message, "text", None):

             await query.edit_message_text(confirmation_text, reply_markup=reply_markup)
        elif getattr(message, "caption", None):

             await query.edit_message_caption(caption=confirmation_text, reply_markup=reply_markup)
        else:

             await update.effective_chat.send_message(confirmation_text, reply_markup=reply_markup)


    except Exception as e:
        structured_logger.error(
            f"Critical error in product confirmation: {str(e)}",
            user_id = update.effective_user.id,
            action="confirm_product_error",
            exception=e,
            context={
                'error_type': type(e).__name__
            }
        )
        await send_message(update, text = "не удалось сохранение. Попробуйте позже или обратитесь в поддержку."
        )
        return ConversationHandler.END


confirm_handler = CallbackQueryHandler(

    confirm_product_callback,
    pattern=r"^confirm_product_\d+$"
)
