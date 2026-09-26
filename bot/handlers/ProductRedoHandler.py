from db.db_async import get_async_session
from db.models import Product,ProductSize
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from sqlalchemy import update as sa_update
from telegram import Update
from utils.logging_config import log_db_update, structured_logger
from utils.access import manager_only, is_owner

RESTART_TEXT = "🚫 Данные удалены. Начните сначала /honey_add"


@manager_only
@log_db_update
async def redo_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message
    tg_user_id = update.effective_user.id

    try:
        product_id = int(query.data.split("_")[-1])

        async with get_async_session() as session:
            # Сбрасываем флаги товара — только у своей карточки (владелец может любую)
            product_filter = [Product.id == product_id]
            if not is_owner(tg_user_id):
                product_filter.append(Product.created_by == tg_user_id)
            result = await session.execute(
                sa_update(Product)
                .where(*product_filter)
                .values(is_draft=True, is_active=False)
            )
            if result.rowcount == 0:
                await query.answer("Карточка не найдена или недоступна.", show_alert=True)
                return ConversationHandler.END
            await query.answer()
            # Сбрасываем размеры
            await session.execute(
                sa_update(ProductSize)
                .where(ProductSize.product_id == product_id)
                .values(is_active=False)
            )

            await session.commit()

        # Определяем тип сообщения (текст или фото)
        if message.text:
            await query.edit_message_text(RESTART_TEXT)
        elif message.caption:
            await query.edit_message_caption(caption=RESTART_TEXT)
        else:
            # Фолбэк — если нет текста и подписи
            await message.reply_text(RESTART_TEXT)



    except Exception as exc:
        structured_logger.error(
            "Error in redo product",
            user_id=tg_user_id,
            action="product_redo_error",
            exception=exc
        )
        await message.reply_text(
            "❌ Произошла ошибка при удалении данных. Попробуйте ещё раз."
        )

    return ConversationHandler.END


redo_handler = CallbackQueryHandler(
    redo_product_callback,
    pattern=r"^redo_product_\d+$"
)
