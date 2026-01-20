from db.db_async import get_async_session
from db.models import Product,ProductSize
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from sqlalchemy import update as sa_update
from telegram import Update
from utils.logging_config import log_db_update


@log_db_update
async def redo_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message

    try:
        product_id = int(query.data.split("_")[-1])
        
        async with get_async_session() as session:
            # Сбрасываем флаги напитка
            await session.execute(
                sa_update(Product)
                .where(Product.id == product_id)
                .values(is_draft=True, is_active=False)
            )
            # Сбрасываем размеры
            await session.execute(
                sa_update(ProductSize)
                .where(ProductSize.product_id == product_id)
                .values(is_active=False)
            )

            await session.commit()

        # Определяем тип сообщения (текст или фото)
        if message.text:
            await query.edit_message_text(
                "🚫 Данные удалены. Начните сначала /create_card"
            )
        elif message.caption:
            await query.edit_message_caption(
                caption="🚫 Данные удалены. Начните сначала /create_card"
            )
        else:
            # Фолбэк — если нет текста и подписи
            await message.reply_text(
                "🚫 Данные удалены. Начните сначала /create_card"
            )



    except Exception as exc:
        await message.reply_text(
            "❌ Произошла ошибка при удалении данных. Попробуйте ещё раз."
        )

    return ConversationHandler.END


redo_handler = CallbackQueryHandler(
    redo_product_callback,
    pattern=r"^redo_product_\d+$"
)
