from pathlib import Path

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, 
    ConversationHandler
)

from db.db_async import get_async_session
from services import tasting
from services.stats import manager_stats_message
from utils.timeutils import utcnow
from utils.user_session_lastorder import create_user, get_user_by_tg_id

from utils.escape import safe_html
from utils.message_tricks import add_message_to_cleanup, cleanup_messages, send_message

from utils.logging_config import structured_logger

from utils.access import is_manager, is_owner
from utils.constants import APIARY_ADDRESS, APIARY_LOCATION

MAX_FIRSTNAME_LENGTH = 50  # users.firstname VARCHAR(50)

# путь от кода, а не абсолютный /bot/…: работает и в контейнере, и в тестах/CI
WELCOME_PHOTO = Path(__file__).resolve().parents[1] / "static" / "images" / "photo_paseka_1.jpg"

FIRST_ENTRY_TEXT = ("Уважаемый Гость\n"
        "Вас приветствует медовый чат-бот 🤖 KrasPolHoney 🍯\n"
        "Если вы впервые у нас, пройдите пожалуйста короткую регистрацию")
WELCOME_TEXT = ("Медовый чат-бот, чтобы выбрать и приобрести продукцию "
                "локальной краснополянской пасеки, "
                "на которой кавказская пчела 🐝 производит настоящий горный мед!🍯\n\n"
                "Чтобы убедиться в этом лично, посетите бесплатную дегустацию!\n\n"
                f"Пасека расположена по адресу {APIARY_ADDRESS}")



NAME_REQUEST, ASK_PHONE, MAIN_MENU = range(3)





async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)
    """Entry point - check if user exists and route accordingly"""


    
    try:
        tg_user = update.effective_user


                   # Log user interaction details
        structured_logger.info(
            "User initiated /start command",
            user_id=tg_user.id,
            action="telegram_start_command",
            context={
                'has_username': bool(tg_user.username),
                'language_code': tg_user.language_code,
                'is_bot': tg_user.is_bot
            }
        )
        user_id = tg_user.id
        # Check if user already exists
        user = await get_user_by_tg_id(user_id)
        # без имени — строка создана назначением в менеджеры до первого /start: проводим регистрацию
        if user is None or not user.firstname:

            # New user - start registration
            structured_logger.info(
                "New user starting registration process",
                user_id=tg_user.id,
                action="registration_start",
                context={'has_username': bool(tg_user.username)}
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
                    'has_name': bool(user.firstname),
                    'last_login': user.updated_at.isoformat() if user.updated_at else None
                }
            )
            return await route_after_login(update, context, user)
                
    except Exception as e:
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
            await update.message.reply_text(
                "Произошла ошибка. Попробуйте позже или обратитесь в поддержку."
            )
            return ConversationHandler.END


async def begin_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_user):
    """Start registration process for new users"""
    user_id = tg_user.id


    try:
        # Store user data for registration process
        context.user_data.update({
            "registration_step": "name",
            "registration_start_time": utcnow()
        })
        structured_logger.info(
            "Registration process initiated",
            user_id=user_id,
            action="registration_begin",
            context={
                'has_username': bool(tg_user.username),
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
    # тот же пользователь, что начал регистрацию; объект Telegram в user_data не храним (persistence)
    tg_user = update.effective_user
    user_id = tg_user.id
    
    try:
        first_name = update.message.text.strip()
        original_input = first_name
            
        if not first_name or first_name.lower() == "использовать никнейм из тг":
            tg_name = (tg_user.first_name or "").strip()
            if not tg_name:
                await update.message.reply_text("В вашем профиле не заполнено поле Имя, напишите, как к вам обращаться:",
                                                 reply_markup=ReplyKeyboardRemove())
                return NAME_REQUEST
            first_name = tg_name
            name_source = "telegram_profile"
        else:
            name_source = "user_input"

        # В БД храним исходный текст, экранируем при выводе в HTML
        first_name = first_name[:MAX_FIRSTNAME_LENGTH]
        context.user_data["first_name"] = first_name
            
        structured_logger.info(
            "User name collected during registration",
            user_id=user_id,
            action="registration_name_collected",
            context={
                'name_source': name_source,
                'name_length': len(first_name),
                'input_length': len(original_input),
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
    # тот же пользователь, что начал регистрацию; объект Telegram в user_data не храним (persistence)
    tg_user = update.effective_user
    user_id = tg_user.id
    
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
            duration = (utcnow() - registration_start).total_seconds()
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
            
        user = await create_user(tg_user, first_name, phone)
        # Уведомление о регистрации по рефералке

        # Log successful registration
        structured_logger.info(
            "User registration completed successfully",
            user_id=user_id,
            action="registration_completed",
            context={
                'new_user_db_id': user.id,
                'has_name': bool(user.firstname),
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
        # Show main menu. Возвращаем результат, иначе диалог застревает в ASK_PHONE
        return await route_after_login(update,context,user)

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
    """Роутинг после регистрации или входа: меню менеджера или покупателя (роль — users.role_id)."""
    await cleanup_messages(context)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass  # колбэк уже мог быть отвечен вызывающим хендлером
    if user is None:
        user_id = update.effective_user.id
        user = await get_user_by_tg_id(user_id)
        if user is None:
            await send_message(update, "Вы ещё не зарегистрированы. Нажмите /start")
            return ConversationHandler.END

    try:
        if await is_manager(user.tg_user_id):
            return await show_manager_menu(update, context, user)
        return await show_customer_menu(update, context, user)
    except Exception as e:
        structured_logger.error(
            f"Error in handle route_after_logging: {str(e)}",
            user_id=user.tg_user_id,
            action="route_after_login_error",
            exception=e
        )
        msg = await send_message(update, "Ошибка на развилке прав.")
        await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
        return ConversationHandler.END


async def show_manager_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    # владелец видит статистику по всем товарам, менеджер — по своим
    async with get_async_session() as session:
        stats_text = await manager_stats_message(
            session, seller_id=None if is_owner(user.tg_user_id) else user.tg_user_id
        )
    await cleanup_messages(context)
    keyboard = [
        [InlineKeyboardButton("✍🏻Добавить мед", callback_data="honey_add"),
        InlineKeyboardButton("🗂 Мой мед", callback_data="honey_get")],
        [InlineKeyboardButton("📨 Мои заказы", callback_data=f"honey_orders_{user.tg_user_id}"),
        InlineKeyboardButton("📣 Приглашение ", callback_data="honey_invite")]
    ]
    # менеджер, назначенный до первого /start, ещё без имени в БД
    name = user.firstname or (update.effective_user.first_name if update.effective_user else "")
    msg = await send_message(update,
        f"👋 Привет, {safe_html(name)}! Статистика по магазину:\n\n{stats_text}",
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
            # effective_message: меню открывается и командой, и колбэком back_menu
            msg = await update.effective_chat.send_photo(
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
        await update.effective_chat.send_message("Ошибка при отображении меню.")
        return ConversationHandler.END


async def handle_show_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Отправляем встроенную карту
    latitude, longitude = APIARY_LOCATION
    await update.effective_chat.send_location(latitude=latitude, longitude=longitude)
    return ConversationHandler.END


async def handle_honey_try(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запись в лист ожидания дегустации; приглашение придёт, когда менеджер назначит дату."""
    query = update.callback_query
    user = await get_user_by_tg_id(update.effective_user.id)
    if user is None:
        await query.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return ConversationHandler.END

    try:
        async with get_async_session() as session:
            record, created = await tasting.signup(session, user.tg_user_id)
            await session.commit()
    except Exception as e:
        structured_logger.error(
            f"Error in sign up for tasting: {str(e)}",
            user_id=user.tg_user_id,
            action="tasting_signup_error",
            exception=e
        )
        await query.answer("Ошибка при записи на дегустацию.", show_alert=True)
        return ConversationHandler.END

    if created:
        text = ("🍯 Вы записаны на дегустацию!\n"
                "Бот пришлёт приглашение за несколько дней.\n"
                "Мероприятие проходит раз в месяц, следите за обновлениями.")
    else:
        text = ("✅ Вы уже записаны на дегустацию!\n"
                "Ожидайте уведомления, бот пришлет приглашение за несколько дней.")
    structured_logger.info(
        "User signed up for tasting",
        user_id=user.tg_user_id,
        action="tasting_signup" if created else "tasting_signup_duplicate",
        context={"signup_id": record.id},
    )
    await query.answer(text, show_alert=True)
    return ConversationHandler.END

# === Отмена ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Действие отменено. Для продолжения работы отправьте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END
