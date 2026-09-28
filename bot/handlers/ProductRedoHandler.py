from db.db_async import get_async_session
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from telegram import Update
from utils.logging_config import structured_logger
from services import catalog
from utils.access import get_actor, manager_only

RESTART_TEXT = "🚫 Данные удалены. Начните сначала /honey_add"


@manager_only
async def redo_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message
    actor = await get_actor(update)

    try:
        product_id = int(query.data.split("_")[-1])

        async with get_async_session() as session:
            # карточка своего магазина (владелец платформы — любая) и её размеры больше не показываются
            if not await catalog.discard_draft(session, product_id, actor.shop_scope):
                await query.answer("Карточка не найдена или недоступна.", show_alert=True)
                return ConversationHandler.END
            await query.answer()

            await session.commit()

        # Определяем тип сообщения (текст или фото)
        if getattr(message, "text", None):
            await query.edit_message_text(RESTART_TEXT)
        elif getattr(message, "caption", None):
            await query.edit_message_caption(caption=RESTART_TEXT)
        else:
            # Фолбэк — если нет текста и подписи
            await update.effective_chat.send_message(RESTART_TEXT)



    except Exception as exc:
        structured_logger.error(
            "Error in redo product",
            user_id=actor.user_id,
            action="product_redo_error",
            exception=exc
        )
        await update.effective_chat.send_message(
            "❌ Произошла ошибка при удалении данных. Попробуйте ещё раз."
        )

    return ConversationHandler.END


redo_handler = CallbackQueryHandler(
    redo_product_callback,
    pattern=r"^redo_product_\d+$"
)
