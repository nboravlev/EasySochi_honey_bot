from db.db_async import get_async_session
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from utils.message_tricks import send_message
from utils.logging_config import structured_logger
from services import catalog
from utils.access import get_actor, manager_only


@manager_only
async def confirm_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message
    actor = await get_actor(update)


    try:
        product_id = int(query.data.split("_")[-1])

        async with get_async_session() as session:
            # публикует менеджер магазина товара (или владелец платформы); удалённую карточку не воскрешаем
            product = await catalog.publish(session, product_id, actor.shop_scope)
            if product is None:
                await query.answer("Карточка не найдена или недоступна.", show_alert=True)
                return ConversationHandler.END
            await query.answer()
            structured_logger.info(
                "New product",
                user_id=actor.user_id,
                product_name=product.name,
                action="product_published",
                context={'product_id': product.id, 'shop_id': product.shop_id}
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
            user_id = actor.user_id,
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
