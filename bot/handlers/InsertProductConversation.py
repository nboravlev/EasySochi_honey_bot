from db.db_async import get_async_session
from db.models.product_types import ProductType
from db.models.products import Product
from db.models.images import Image
from db.models.productsize_images import ProductsizeImage
from db.models.packages import Package
from db.models.product_sizes import ProductSize
from db.models.sizes import Size

from sqlalchemy.orm import selectinload

from sqlalchemy import select

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
from utils.message_tricks import send_message,add_message_to_cleanup,cleanup_messages
from utils.escape import safe_html
from utils.full_view_manager import render_card
from utils.call_size import init_size_map, get_size_id_async
from utils.preprocess_foto import preprocess_photo_crop_center
from utils.access import manager_only
from utils.constants import MAX_PRICE, MAX_PRODUCT_NAME_LENGTH
from utils.validation import parse_price
from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)



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

    with LoggingContext("start_add_object", user_id=update.effective_user.id):
        try:
            if update.callback_query:
                query = update.callback_query
                await query.answer()
                await query.edit_message_reply_markup(reply_markup=None)
                send_to = query.message
            else:
                send_to = update.message

            keyboard = [[KeyboardButton("Сохранить название")]]
            await send_to.reply_text(
                "Введите название продукта:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
            structured_logger.info("Prompted user for product name")
            return PRODUCT_NAME
        except Exception as e:
            structured_logger.error("Error in start_add_object", exception=e)
            await update.message.reply_text("Ошибка при старте добавления продукта.")
            return ConversationHandler.END


async def handle_object_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip() or "Просто мед"
    if len(name) > MAX_PRODUCT_NAME_LENGTH:
        await update.message.reply_text(
            f"Название слишком длинное. Уложитесь в {MAX_PRODUCT_NAME_LENGTH} символов:"
        )
        return PRODUCT_NAME
    context.user_data["name"] = name
    with LoggingContext("handle_object_name", user_id=update.effective_user.id):
        try:
            async with get_async_session() as session:
                types = (await session.execute(ProductType.__table__.select())).fetchall()
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
    with LoggingContext("handle_object_type", user_id=update.effective_user.id):
        structured_logger.info(f"User selected product type {type_id}")
        # Инициализация размеров
        context.user_data["current_size_index"] = 0
        context.user_data["sizes"] = []
        return await ask_size(update, context)


async def ask_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        target = update.callback_query.message
        await update.callback_query.answer()
    else:
        target = update.message

    idx = context.user_data.get("current_size_index", 0)
    if idx >= len(SIZES):
        if not context.user_data.get("sizes"):
            context.user_data["sizes"] = []
            context.user_data["current_size_index"] = 0
            await target.reply_text("⚠️ Укажите хотя бы один размер с ценой. Начнем заново.")
            return await ask_size(update, context)
        else:
            msg = await target.reply_text(
                "Введите описание продукта:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Пропустить описание")]], resize_keyboard=True, one_time_keyboard=True)
            )
            await add_message_to_cleanup(context, msg.chat_id, msg.message_id)
            return PRODUCT_DESCRIPTION

    size = SIZES[idx]
    keyboard = ReplyKeyboardMarkup([["Да", "Нет"]], resize_keyboard=True, one_time_keyboard=True)
    await target.reply_text(f"Добавляем размер {size} Укажите цену:", reply_markup=keyboard)
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
    tg_user_id = context.user_data.get("tg_user_id") or update.effective_user.id
    if not photos:
        structured_logger.warning("No photos uploaded", user_id=tg_user_id)
        await update.message.reply_text("Вы не загрузили ни одного фото.")
        return PRODUCT_PHOTO

    async with get_async_session() as session:
        product = Product(
            name=context.user_data['name'],
            type_id=context.user_data['type_id'],
            description=context.user_data['description'],
            created_by=tg_user_id
        )
        session.add(product)
        await session.flush()
        structured_logger.info("Product object created in DB session", user_id=tg_user_id)

        for file_id in photos:
            session.add(Image(product_id=product.id, tg_file_id=file_id))
            structured_logger.info("Photo linked to product", user_id=tg_user_id, context={"file_id": file_id})

        for item in context.user_data.get("sizes", []):
            size_name = item["size"]
            price = item["price"]
            try:
                size_id = await get_size_id_async(size_name)
                session.add(ProductSize(product_id=product.id, size_id=size_id, price=price))
            except KeyError:
                structured_logger.error(f"Size {size_name} not found", user_id=tg_user_id)
                await update.message.reply_text(f"Размер '{size_name}' не найден.")
                await session.rollback()
                return ConversationHandler.END
        await session.flush() 
        
        stmt = (
            select(Product)
            .where(Product.id == product.id)
            .options(
                selectinload(Product.product_sizes).selectinload(ProductSize.sizes),
                selectinload(Product.images),
                selectinload(Product.product_type),
            )
        )
        result = await session.execute(stmt)
        product = result.scalars().first()

        text, _, markup = render_card(product)

        if product.images:
            await update.message.reply_photo(
                photo=str(product.images[0].tg_file_id),
                caption=text,
                parse_mode="HTML",
                reply_markup=markup
            )
        else:
            await update.message.reply_text(
                text=text,
                parse_mode="HTML",
                reply_markup=markup
            )
        await session.commit()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Вы вышли из создания меда.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    structured_logger.info("User canceled add product scenario", user_id=update.effective_user.id)
    return ConversationHandler.END

