from db.db_async import get_async_session
from services import catalog

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
    ConversationHandler
)
from utils.message_tricks import add_message_to_cleanup
from utils.escape import safe_html
from utils.full_view_manager import render_card
from utils.preprocess_foto import preprocess_photo_crop_center
from utils.access import get_actor, manager_only
from utils.constants import MAX_PRICE, MAX_PRODUCT_NAME_LENGTH
from utils.validation import parse_price
from utils.logging_config import structured_logger



# Состояния
(
    PRODUCT_NAME,
    PRODUCT_TYPE,
    PRODUCT_SIZE,
    PRODUCT_DESCRIPTION,
    PRODUCT_PHOTO
) = range(5)

SIZES = ["0.5кг","1.0кг","1.5кг"]
MAX_DESCRIPTION_LENGTH = 255


# ====== START INSERT ======

@manager_only
async def start_add_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #await cleanup_messages(context)

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)

        keyboard = [[KeyboardButton("Сохранить название")]]
        await update.effective_chat.send_message(
            "Введите название продукта:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        structured_logger.info("Prompted user for product name")
        return PRODUCT_NAME
    except Exception as e:
        structured_logger.error("Error in start_add_object", exception=e)
        await update.effective_chat.send_message("Ошибка при старте добавления продукта.")
        return ConversationHandler.END


async def handle_object_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip() or "Просто мед"
    if len(name) > MAX_PRODUCT_NAME_LENGTH:
        await update.message.reply_text(
            f"Название слишком длинное. Уложитесь в {MAX_PRODUCT_NAME_LENGTH} символов:"
        )
        return PRODUCT_NAME
    context.user_data["name"] = name
    try:
        async with get_async_session() as session:
            types = await catalog.all_types(session)
            keyboard = [[InlineKeyboardButton(t.name, callback_data=str(t.id))] for t in types]
            reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Название продукта: <b>{safe_html(name)}</b>\nВыберите сорт меда:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        structured_logger.info(f"User entered product name: {name}")
        return PRODUCT_TYPE
    except Exception as e:
        structured_logger.error("Error in handle_object_name", exception=e)
        await update.message.reply_text("Ошибка при обработке названия продукта.")
        return ConversationHandler.END


async def handle_object_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    type_id = int(query.data)
    context.user_data["type_id"] = type_id
    structured_logger.info(f"User selected product type {type_id}")
    # Инициализация размеров
    context.user_data["current_size_index"] = 0
    context.user_data["sizes"] = []
    return await ask_size(update, context)


async def ask_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    target = update.effective_chat  # сообщение из колбэка может быть недоступно (InaccessibleMessage)

    idx = context.user_data.get("current_size_index", 0)
    if idx >= len(SIZES):
        if not context.user_data.get("sizes"):
            context.user_data["sizes"] = []
            context.user_data["current_size_index"] = 0
            await target.send_message("⚠️ Укажите хотя бы один размер с ценой. Начнем заново.")
            return await ask_size(update, context)
        else:
            msg = await target.send_message(
                "Введите описание продукта:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Пропустить описание")]], resize_keyboard=True, one_time_keyboard=True)
            )
            await add_message_to_cleanup(context, msg.chat_id, msg.message_id)
            return PRODUCT_DESCRIPTION

    size = SIZES[idx]
    keyboard = ReplyKeyboardMarkup([["Да", "Нет"]], resize_keyboard=True, one_time_keyboard=True)
    await target.send_message(f"Добавляем размер {size} Укажите цену:", reply_markup=keyboard)
    structured_logger.info(f"Prompted user for size {size}")
    return PRODUCT_SIZE


async def handle_object_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["current_size_index"]
    size = SIZES[idx]
    raw_text = (update.message.text or "").strip().lower()
    if raw_text == "нет":
        context.user_data["current_size_index"] += 1
        return await ask_size(update, context)
    price = parse_price(raw_text)
    if price is None:
        await update.message.reply_text(f"Введите цену числом от 1 до {MAX_PRICE:,} ₽ (или «Нет»).".replace(",", " "))
        return PRODUCT_SIZE

    context.user_data["sizes"].append({"size": size, "price": price})
    context.user_data["current_size_index"] += 1
    structured_logger.info(f"User set price for size {size}: {price}")
    return await ask_size(update, context)


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_desc = (update.message.text or "").strip()
    description = raw_desc[:MAX_DESCRIPTION_LENGTH] if raw_desc.lower() not in ("", "пропустить описание") else "Просто хороший мед без специального описания. 👍"
    context.user_data["description"] = description
    context.user_data["photos"] = []
    await update.message.reply_text(
        "Загрузите фото продукта. После загрузки нажмите «Готово».",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Готово")]], resize_keyboard=True, one_time_keyboard=True)
    )
    structured_logger.info(f"Product description set: {description}")
    return PRODUCT_PHOTO


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    original_file_id = photo.file_id
    new_file_id = await preprocess_photo_crop_center(original_file_id, context.bot, update.effective_chat.id)
    context.user_data.setdefault("photos", []).append(new_file_id)
    await update.message.reply_text(
        f"Фото добавлено ({len(context.user_data['photos'])} шт.). Нажмите «Готово».",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Готово")]], resize_keyboard=True, one_time_keyboard=True)
    )
    structured_logger.info(f"Photo added: {new_file_id} (total {len(context.user_data['photos'])})")
    return PRODUCT_PHOTO


async def handle_photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photos = context.user_data.get("photos", [])
    actor = await get_actor(update)
    if not photos:
        structured_logger.warning("No photos uploaded", user_id=actor.user_id)
        await update.message.reply_text("Вы не загрузили ни одного фото.")
        return PRODUCT_PHOTO

    # товар создаётся в магазине менеджера (у владельца платформы — в магазине-витрине)
    shop_id = await actor.work_shop_id()
    if shop_id is None:
        await update.message.reply_text("Не удалось определить магазин для товара. Обратитесь к владельцу платформы.")
        return ConversationHandler.END

    async with get_async_session() as session:
        try:
            product = await catalog.create_draft_product(
                session,
                shop_id=shop_id,
                author_id=actor.user_id,
                name=context.user_data["name"],
                type_id=context.user_data["type_id"],
                description=context.user_data["description"],
                prices=[(item["size"], item["price"]) for item in context.user_data.get("sizes", [])],
                photo_file_ids=photos,
            )
        except LookupError as e:
            structured_logger.error(str(e), user_id=actor.user_id, action="product_create_failed")
            await update.message.reply_text(f"Не удалось создать карточку: {e}")
            return ConversationHandler.END
        await session.commit()

    structured_logger.info(
        "Product draft created", user_id=actor.user_id, action="product_draft_created",
        context={"product_id": product.id, "shop_id": shop_id, "photos": len(photos)},
    )
    text, _, markup = render_card(product)
    if product.images:
        await update.message.reply_photo(
            photo=str(product.images[0].tg_file_id), caption=text, parse_mode="HTML", reply_markup=markup
        )
    else:
        await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Вы вышли из создания меда.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    structured_logger.info("User canceled add product scenario", user_id=update.effective_user.id)
    return ConversationHandler.END

