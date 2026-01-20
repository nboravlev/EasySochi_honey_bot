from telegram import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    Update, 
    ReplyKeyboardRemove, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler
)
from db.db_async import get_async_session
from utils.logging_config import structured_logger, LoggingContext
from utils.user_session_lastorder import get_user_by_tg_id, create_session
from utils.message_tricks import add_message_to_cleanup, cleanup_messages, send_message


DEG_PHOTO = "/bot/static/images/paseka.jpg"

DEG_TEXT = ("Предварительная запись на дегустацию одобрена.\n"
                "Дегустации проходят раз в месяц.\n"
                "Бот пришлет вам уведомление о дате следующей акции,\n"
                "Следите за обновлениями.\n"
                "Пасека расположена по адресу Красная Поляна, ул. Плотинная, д.4\n")

LAT = '43.672805'
LON = '40.200094'

async def degustation_request_handler_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)
    user_id = update.effective_user.id
    user = await get_user_by_tg_id(user_id)
    with LoggingContext("sign_4_degustation", user_id=user_id):
        try:
            query = update.callback_query
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)
            role_id = 3
            session = await create_session(user.tg_user_id, role_id)
            context.user_data["session_id"] = session.id
            structured_logger.info("signing_for_degustation",
                    user_id = user_id,
                    action = "signing_for_degustation")
            return await show_degustation_info(update, context, user)
        

        except Exception as e:
            structured_logger.error("Error in signing_for_degustation", exception=e)
            await update.message.reply_text("Ошибка при записи на дегустацию.")
            return ConversationHandler.END
        
async def show_degustation_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """Запись на дегустацию"""
    try:
        # 1. Отправляем фото с подписью
        with open(DEG_PHOTO, "rb") as f:

            action_keyboard = [InlineKeyboardButton("📍 Показать на карте", callback_data="show_map")]
            keyboard = InlineKeyboardMarkup(action_keyboard)
            await update.message.reply_photo(
                photo=f,
                caption=DEG_TEXT,
                reply_markup=keyboard
            )


        structured_logger.info(
            "Customer menu rendered successfully",
            user_id=user.tg_user_id,
            action="show_customer_menu_end",

        )

        return 

    except Exception as e:
        structured_logger.error(
            f"Error in show_customer_menu: {str(e)}",
            user_id=user.tg_user_id,
            action="customer_menu_error",
            exception=e
        )
        await update.message.reply_text("Ошибка при отображении меню.")
        return ConversationHandler.END


async def handle_show_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    print("DEBUG: handle_show_map triggered")
    await query.answer()

    # Отправляем встроенную карту
    await query.message.reply_location(
        latitude=float(LAT),
        longitude=float(LON)
    )
    return ConversationHandler.END

# === Отмена ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌Для продолжения работы отправьте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END


degustation_handler = CallbackQueryHandler(
    degustation_request_handler_start,
    pattern=r"^honey_try$"
)