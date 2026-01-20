from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler
)

from sqlalchemy import update as sa_update, select, desc
from datetime import datetime
from sqlalchemy.orm import selectinload

from db.db_async import get_async_session

from db.models import User, Session, Role, Product, Order


from utils.user_session_lastorder import (
    get_user_by_tg_id, 
    create_user, 
    create_session, 
    get_actual_session_by_tg_id)

from utils.get_orders_products_statistics import get_manager_stats_message

from utils.escape import safe_html
from utils.message_tricks import add_message_to_cleanup, cleanup_messages, send_message

from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)

import os


MANAGER_LIST = [
    int(m.strip(" []")) for m in os.getenv("MANAGER_LIST", "").split(",") if m.strip(" []")
]

MENU_URL = []
WELCOME_PHOTO = "/bot/static/images/photo_paseka_1.jpg"

FIRST_ENTRY_TEXT = ("Уважаемый Гость\n"
        "Вас приветствует медовый чат-бот 🤖 KrasPolHoney 🍯\n"
        "Если вы впервые у нас, пройдите пожалуйста короткую регистрацию")
WELCOME_TEXT = ("Медовый чат-бот, чтобы выбрать и приобрести продукцию "
                "локальной краснополянской пасеки, "
                "на которой кавказская пчела 🐝 производит настоящий горный мед!🍯\n\n"
                "Чтобы убедиться в этом лично, посетите бесплатную дегустацию!\n\n"
                "Пасека расположена по адресу Красная Поляна, ул.Плотинная, д.4")



NAME_REQUEST, ASK_PHONE, MAIN_MENU,CALLBACK_HANDLER = range(4)



def chunk_buttons(buttons, n=2):
    """Group buttons into rows of n buttons each"""
    return [buttons[i:i+n] for i in range(0, len(buttons), n)]



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)
    """Entry point - check if user exists and route accordingly"""


    with LoggingContext("user_start_command", 
                       command="start", update_type="telegram") as log_ctx:
    
        try:
            tg_user = update.effective_user
            print(f"DEBUG-initial-user: {tg_user}")


                       # Log user interaction details
            structured_logger.info(
                "User initiated /start command",
                user_id=tg_user.id,
                action="telegram_start_command",
                context={
                    'username': tg_user.username,
                    'first_name': tg_user.first_name,
                    'language_code': tg_user.language_code,
                    'is_bot': tg_user.is_bot
                }
            )
            user_id = tg_user.id
            print(user_id)
            # Check if user already exists
            user = await get_user_by_tg_id(user_id)
            print(f"DEBUG_User:{user}")
            if user is None:

                # New user - start registration
                structured_logger.info(
                    "New user starting registration process",
                    user_id=tg_user.id,
                    action="registration_start",
                    context={'tg_username': tg_user.username}
                )
                return await begin_registration(update, context, tg_user)
            else:
                # Existing user - show main menu
                structured_logger.info(
                    "Existing user accessing main menu",
                    user_id=tg_user.id,
                    action="main_menu_access",
                    context={
                        'user_db_id': user.id,
                        'user_name': user.firstname,
                        'last_login': user.updated_at.isoformat() if user.updated_at else None
                    }
                )
                return await route_after_login(update, context, user)
                
        except Exception as e:
                # LoggingContext will automatically log the error with full context
                structured_logger.error(
                    f"Critical error in start handler: {str(e)}",
                    user_id = tg_user.id,
                    action="start_command_error",
                    exception=e,
                    context={
                        'tg_user_id': tg_user.id,
                        'error_type': type(e).__name__
                    }
                )
                print(e)
                await update.message.reply_text(
                    "Произошла ошибка. Попробуйте позже или обратитесь в поддержку."
                )
                return ConversationHandler.END


async def begin_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_user):
    """Start registration process for new users"""
    user_id = tg_user.id


    with LoggingContext("registration_flow", user_id=user_id, 
                    step="begin", process="user_registration") as log_ctx:
        try:
            # Store user data for registration process
            context.user_data.update({
                "tg_user": tg_user,
                "registration_step": "name",
                "registration_start_time": datetime.utcnow()
            })
            structured_logger.info(
                "Registration process initiated",
                user_id=user_id,
                action="registration_begin",
                context={
                    'tg_username': tg_user.username,
                    'tg_first_name': tg_user.first_name,
                    'has_profile_photo': tg_user.has_profile_photo if hasattr(tg_user, 'has_profile_photo') else None
                }
            )
            try:
            # Send welcome message
                with open(WELCOME_PHOTO, "rb") as f:
                    await update.message.reply_photo(
                        photo=f,
                        caption=f"{FIRST_ENTRY_TEXT}"
                    )
                structured_logger.debug(
                    "Welcome photo sent successfully",
                    user_id=user_id,
                    action="welcome_photo_sent"
                )
            except FileNotFoundError as e:
                structured_logger.warning(
                    f"Welcome photo not found: {WELCOME_PHOTO}",
                    user_id=user_id,
                    action="welcome_photo_missing",
                    exception=e
                )
                await update.message.reply_text(f"{FIRST_ENTRY_TEXT}")
                
            # Ask for first name - with option to use Telegram name
            keyboard = [[KeyboardButton("Использовать никнейм из ТГ")]]
            await update.message.reply_text(
                "Как к вам обращаться? Напишите ваше имя или выберите вариант ниже:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
            return NAME_REQUEST
            
        except Exception as e:
            structured_logger.error(
                f"Error in begin_registration: {str(e)}",
                user_id=user_id,
                action="registration_begin_error",
                exception=e
            )
            await update.message.reply_text("Ошибка при начале регистрации.")
            return ConversationHandler.END
    
async def handle_name_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle name input during registration"""
    tg_user = context.user_data.get("tg_user")
    user_id = tg_user.id if tg_user else None
    
    with LoggingContext("registration_name_step", user_id=user_id) as log_ctx:
        try:
            first_name = update.message.text.strip()
            original_input = first_name
            
            if not first_name or first_name.lower() == "использовать никнейм из тг":
                tg_name = tg_user.first_name
                if not tg_name == None:
                    await update.message.reply_text("В вашем профиле не заполнено поле Имя, напишите, как к вам обращаться:",
                                                     reply_markup=ReplyKeyboardRemove())
                    return NAME_REQUEST
                first_name = tg_name.strip()
                name_source = "telegram_profile"
            else:
                first_name = safe_html(first_name)
                name_source = "user_input"

            context.user_data["first_name"] = first_name
            
            structured_logger.info(
                "User name collected during registration",
                user_id=user_id,
                action="registration_name_collected",
                context={
                    'name_source': name_source,
                    'name_length': len(first_name),
                    'original_input': original_input[:50],  # Limit for privacy
                    'sanitized_name': first_name[:50]
                }
            )

            keyboard = [
                [KeyboardButton("📞 Отправить номер телефона", request_contact=True)],
                ["Пропустить"]
            ]
            msg = await update.message.reply_text(
                f"Приятно познакомиться, {first_name}!\n\n"
                "Пожалуйста, поделитесь номером телефона, для лучшего сервиса\n"
                "(или нажмите 'Пропустить'):",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
            return ASK_PHONE
            
        except Exception as e:
            structured_logger.error(
                f"Error in handle_name_request: {str(e)}",
                user_id=user_id,
                action="registration_name_error",
                exception=e
            )
            await update.message.reply_text("Ошибка при обработке имени.")
            return ConversationHandler.END
        
async def handle_phone_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number during registration"""
    tg_user = context.user_data.get("tg_user")
    user_id = tg_user.id if tg_user else None
    
    with LoggingContext("registration_phone_step", user_id=user_id) as log_ctx:
        try:
            phone = None
            phone_source = None
            
            if update.message.contact:
                phone = update.message.contact.phone_number
                phone_source = "telegram_contact"
                structured_logger.info(
                    "Phone number provided via Telegram contact",
                    user_id=user_id,
                    action="phone_via_contact",
                    context={'phone_country_code': phone[:3] if phone else None}
                )
            elif update.message.text == "Пропустить":
                phone = None
                phone_source = "skipped"
                structured_logger.info(
                    "User skipped phone number entry",
                    user_id=user_id,
                    action="phone_skipped"
                )
            else:
                msg = await update.message.reply_text("Пожалуйста, нажмите кнопку отправки телефона или 'Пропустить':")
                await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
                return ASK_PHONE

            # Complete user registration
            first_name = context.user_data.get("first_name")
            registration_start = context.user_data.get("registration_start_time")
            
            # Calculate registration duration
            if registration_start:
                #start_time = datetime.fromisoformat(registration_start)
                duration = (datetime.utcnow() - registration_start).total_seconds()
            else:
                duration = None
            
            structured_logger.info(
                "Starting user creation in database",
                user_id=user_id,
                action="user_creation_start",
                context={
                    'has_phone': phone is not None,
                    'phone_source': phone_source,
                    'registration_duration': duration
                }
            )
            
            # This function should have @log_db_insert decorator
            user = await create_user(tg_user, first_name, phone)
            # Уведомление о регистрации по рефералке

            # Log successful registration
            structured_logger.info(
                "User registration completed successfully",
                user_id=user_id,
                action="registration_completed",
                context={
                    'new_user_db_id': user.id,
                    'user_name': user.firstname,
                    'has_phone': user.phone_number is not None,
                    'registration_duration': duration
                }
            )
            
            msg=await update.message.reply_text(
                f"✅ Регистрация завершена!\n"
                f"{'Номер телефона сохранён.' if phone else 'Регистрация без номера телефона.'}",
                reply_markup=ReplyKeyboardRemove()
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
            # Show main menu
            await route_after_login(update,context,user)
            
        except Exception as e:
            structured_logger.error(
                f"Error in handle_phone_registration: {str(e)}",
                user_id=user_id,
                action="registration_phone_error",
                exception=e,
                context={
                    'phone_provided': update.message.contact is not None,
                    'message_text': update.message.text[:50] if update.message.text else None
                }
            )
            msg = await update.message.reply_text("Ошибка при сохранении данных.")
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
            return ConversationHandler.END

async def route_after_login(update: Update, context: ContextTypes.DEFAULT_TYPE, user = None):
    """Роутинг после регистрации или входа с созданием сессии"""
    await cleanup_messages(context)
    if user is None:
        user_id = update.effective_user.id
        user = await get_user_by_tg_id(user_id)

    print(f"DEBUG: user_id = {user.tg_user_id}\nMANAGER_LIST = {MANAGER_LIST}")
    try:
        if user.tg_user_id in MANAGER_LIST:
            role_id = 4
            session = await create_session(user.tg_user_id, role_id)
            context.user_data["session_id"] = session.id
            return await show_manager_menu(update, context, user)
        else:
            return await show_customer_menu(update, context, user)


    except Exception as e:
        structured_logger.error(
            f"Error in handle route_after_logging: {str(e)}"
        )
        msg = await update.message.reply_text("Ошибка на развилке прав.")
        await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
        return ConversationHandler.END


async def show_manager_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    stats_text = await get_manager_stats_message(user.tg_user_id)
    await cleanup_messages(context)
    keyboard = [
        [InlineKeyboardButton("✍🏻Добавить мед", callback_data="honey_add"),
        InlineKeyboardButton("🗂 Мой мед", callback_data="honey_get")],
        [InlineKeyboardButton("📨 Мои заказы", callback_data=f"honey_orders_{user.tg_user_id}"),
        InlineKeyboardButton("📣 Приглашение ", callback_data="honey_invite")]
    ]
    msg = await send_message(update,
        f"👋 Привет, {user.firstname}! Статистика по магазину:\n\n {stats_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode = "HTML"
    )
    await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
    return ConversationHandler.END


async def show_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """Главное меню для покупателя"""
    try:
        # 1. Отправляем фото с подписью
        with open(WELCOME_PHOTO, "rb") as f:
            location_keyboard = [
            [InlineKeyboardButton("📍 Показать на карте", callback_data="show_map")]
        ]
            action_keyboard = [
            [InlineKeyboardButton("🍯 Выбрать мед", callback_data="honey_buy"),
            InlineKeyboardButton("Дегустация 🍽", callback_data="honey_try")]            
        ]
            keyboard = InlineKeyboardMarkup(location_keyboard+action_keyboard)
            msg = await update.message.reply_photo(
                photo=f,
                caption=WELCOME_TEXT,
                reply_markup=keyboard
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

        structured_logger.info(
            "Customer menu rendered successfully",
            user_id=user.tg_user_id,
            action="show_customer_menu_end",

        )

        return ConversationHandler.END

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
    LAT = '43.672805'
    LON = '40.200094'
    query = update.callback_query
    print("DEBUG: handle_show_map triggered")
    await query.answer()

    # Отправляем встроенную карту
    await query.message.reply_location(
        latitude=float(LAT),
        longitude=float(LON)
    )
    return ConversationHandler.END   

async def handle_honey_try(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from utils.logging_config import structured_logger
    query = update.callback_query

    #await query.answer()

    user_id = update.effective_user.id
    user = await get_user_by_tg_id(user_id)
    if user:
        try:
            existing_session_id = await get_actual_session_by_tg_id(user.tg_user_id,role_id=3)
            if existing_session_id:
                text = ("✅ Вы уже записаны на дегустацию!\n"
                        "Ожидайте уведомления, бот пришлет приглашение за несколько дней.")
                structured_logger.info(
                    "User already registered for tasting",
                    user_id=user.tg_user_id,
                    session_id = existing_session_id,
                    action="honey_try_duplicate"
                )
            else:
                # создаём сессию с role_id = 3
                session = await create_session(user.tg_user_id, role_id=3)
                context.user_data["session_id"] = session.id

                text = ("🍯 Вы записаны на дегустацию!\n"
                    "Бот пришлёт приглашение за несколько дней.\n"
                    "Мероприятие проходит раз в месяц, следите за обновлениями.")
                structured_logger.info(
                "User signed up for tasting",
                user_id=user.tg_user_id,
                session_id = session.id,
                action="honey_try",
            )

            #await send_message(update,text)
            await query.answer(text, show_alert = True)
            
            return ConversationHandler.END
        
        except Exception as e:
            structured_logger.error(
                f"Error in sigh up for tasting: {str(e)}",
                user_id=user.tg_user_id,
                action="honey_try",
                exception=e
            )
            #await send_message(update,text=("Ошибка при записи на дегустацию."))
            await query.answer("Ошибка при записи на дегустацию.", show_alert=True)
            return ConversationHandler.END
    else:
        await send_message(update,text="пользователь не найден")

    return ConversationHandler.END

# === Отмена ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Действие отменено. Для продолжения работы отправьте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END
