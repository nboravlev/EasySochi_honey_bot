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
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime
from handlers.RegistrationConversation import route_after_login

from utils.manager_lk_collection import fetch_seller_products, get_manager_product_sizes_keyboard
from utils.message_tricks import send_message, add_message_to_cleanup, cleanup_messages

from utils.logging_config import structured_logger, LoggingContext

from db.models import ProductSize,Product,Session

import os


(VIEW_PRODUCTS,
EDIT_PRICE_PROMPT,
EDIT_PRICE_WAIT_INPUT) = range(3)

OWNER_ID = os.getenv("OWNER_ID")
if not (OWNER_ID):
    raise RuntimeError("Owner chat id did not set in environment variables")


async def handle_manager_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = getattr(update, "callback_query", None)
    tg_user = update.effective_user
    tg_chat = update.effective_chat

    # Определяем, откуда вызвали
    is_callback = query is not None
    if is_callback:
        await query.answer()
        
    try:
        tg_user_id = update.effective_user.id
        is_admin = str(tg_user_id) == str(OWNER_ID)
        products = await fetch_seller_products(tg_user_id,is_admin)

        if not products:
            await update.effective_message.reply_text("❌ Ваших товаров не найдено в базе.")
            return ConversationHandler.END

        for product in products:
            # Получаем размеры и клавиатуру
            sizes, keyboard_markup, image_file_id = await get_manager_product_sizes_keyboard(product.id)

            caption = f"<b>{product.name}</b> ||сорт: {product.product_type.name}\n{product.description or 'Без описания'}"

            if image_file_id:
                sent = await update.effective_message.reply_photo(
                    photo=image_file_id,
                    caption=caption,
                    reply_markup=keyboard_markup,
                    parse_mode="HTML"
                )
            else:
                sent = await update.effective_message.reply_text(
                    caption,
                    reply_markup=keyboard_markup,
                    parse_mode="HTML"
                )
                # сохраняем id отправленного сообщения
            await add_message_to_cleanup(context,sent.chat_id,sent.message_id)
    
        return VIEW_PRODUCTS

    except Exception as e:
        structured_logger.error(
            f"Error in manager products: {str(e)}",
            user_id=tg_user_id,
            action="view_manager_products",
            exception=e
        )
        await send_message(update,text=("Ошибка при демонстрации товаров."))
        return ConversationHandler.END 


#======редактирование карточки товара=========
async def handle_product_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tg_user_id = update.effective_user.id
    productsize_id = int(query.data.split("_")[-1])

    with LoggingContext("product_upgrade_init", user_id=tg_user_id, productsize_id=productsize_id):
        async with get_async_session() as session:
            result = await session.execute(
                select(ProductSize).options(selectinload(ProductSize.product),
                                            selectinload(ProductSize.sizes))
                                .where(ProductSize.id == productsize_id)
            )
            productsize = result.scalar_one_or_none()

            if not productsize:
                structured_logger.warning(
                    f"Product {productsize.product.name}({productsize.sizes.name}) not found for upgrade.",
                    user_id=tg_user_id,
                    action="productsize_upgrade_not_found",
                    context={'productsize_id': productsize.id}
                )
                await query.message.edit_text("❌ Товар не найден.")
                return VIEW_PRODUCTS

            if productsize.product.created_by != tg_user_id:
                structured_logger.warning(
                    f"Unauthorized edit attempt by user {tg_user_id}",
                    user_id=tg_user_id,
                    action="unauthorized_product_edit_attempt",
                    context={'productsize_id': productsize.id}
                )
                await send_message(update,"🚫 У вас нет прав для редактирования этого товара.")
                return ConversationHandler.END

            structured_logger.info(
                "User initiated product price edit.",
                user_id=tg_user_id,
                action="apartment_upgrade_start",
                context={'productsize_id': productsize.id, 'current_price': productsize.price}
            )

            # Сохраняем id товара для последующих шагов
            context.user_data["edit_productsize_id"] = productsize_id
            context.user_data["sizename"] = productsize.sizes.name
            text = (
                f"🛠 Вы можете отредактировать только <b>стоимость</b> товара.\n\n"
                f"💰 Текущая цена: <b>{productsize.price} ₽/{productsize.sizes.name}кг</b>\n\n"
                f"Выберите действие:"
            )

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✏️ Редактировать", callback_data="edit_price_start"),
                    InlineKeyboardButton("🔙 Вернуться назад", callback_data="honey_get")
                ]
            ])

            msg = await send_message(update,text, reply_markup=keyboard, parse_mode="HTML")
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
            return EDIT_PRICE_PROMPT
        
async def handle_edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.edit_text(
        "💬 Введите новую стоимость в рублях (только число):",
        reply_markup=None
    )
    return EDIT_PRICE_WAIT_INPUT

async def handle_new_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user_id = update.effective_user.id
    new_price_text = update.message.text.strip()
    productsize_id = context.user_data.get("edit_productsize_id")
    sizename = context.user_data.get("sizename")

    with LoggingContext("product_price_edit", user_id=tg_user_id, productsize_id=productsize_id):
        try:
            new_price = float(new_price_text)
            if new_price <= 0:
                raise ValueError("Price must be positive.")
        except ValueError:
            structured_logger.warning(
                "Invalid price input.",
                user_id=tg_user_id,
                action="invalid_price_input",
                context={'input_value': new_price_text}
            )
            await update.message.reply_text("❌ Введите корректное положительное число.")
            return EDIT_PRICE_WAIT_INPUT

        async with get_async_session() as session:
            result = await session.execute(
                select(ProductSize).where(ProductSize.id == productsize_id)
            )
            productsize = result.scalar_one_or_none()

            if not productsize:
                await update.message.reply_text("⚠️ Объект не найден.")
                return VIEW_PRODUCTS

            # Обновляем цену
            old_price = productsize.price
            productsize.price = new_price
            productsize.updated_at = datetime.utcnow()
            await session.commit()

            structured_logger.info(
                f"Product price updated from {old_price} to {new_price}",
                user_id=tg_user_id,
                action="apartment_price_updated",
                context={
                    'apartment_id': productsize.id,
                    'old_price': old_price,
                    'new_price': new_price
                }
            )

            # Уведомляем пользователя и возвращаем к списку
            await update.message.reply_text(
                f"✅ Стоимость обновлена: <b>{new_price:.0f} ₽/{sizename}кг</b>",
                parse_mode="HTML"
            )

            # Сразу обновляем карточки
            await handle_manager_products(update, context)
            return VIEW_PRODUCTS
        
#=======Отмена удаления====
async def cancel_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        await query.delete_message()   # Полностью удаляет сообщение с кнопками
    except Exception:
        # fallback: если удалить нельзя, то просто убираем кнопки
        await query.edit_message_reply_markup(reply_markup=None)

    return VIEW_PRODUCTS

#=======подтверждение удаления =======

async def confirm_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[-1])

    keyboard = [
        [
            InlineKeyboardButton("❌ Удалить", callback_data=f"delete_confirm_{product_id}"),
            InlineKeyboardButton("↩️ Отмена", callback_data="delete_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        f"Вы уверены, что хотите удалить товар №{product_id}?",
        reply_markup=reply_markup
    )
    return VIEW_PRODUCTS

#=======подтверждение получено ==========
async def delete_product_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[-1])
    tg_user_id = update.effective_user.id

    ACTIVE_BOOKING_STATUSES = [1,2,3,4]
    
    with LoggingContext("product_deletion", user_id=tg_user_id, 
                       product_id=product_id) as log_ctx:
        
        structured_logger.warning(
            f"User attempting to delete product {product_id}",
            user_id=tg_user_id,
            action="product_deletion_attempt",
            context={'product_id': product_id}
        )
        
        async with get_async_session() as session:
            result = await session.execute(
                select(Product)
                .options(
                    selectinload(Product.product_sizes).selectinload(ProductSize.orders)
                )
                .where(Product.id == product_id)
            )
            product = result.scalar_one_or_none()

            if not product:
                await update.callback_query.message.reply_text("❌ Товар не найден.")
                return VIEW_PRODUCTS

            # Собираем все активные заказы через вложенные циклы
            active_orders = [
                order
                for size in product.product_sizes
                for order in size.orders
                if order.status_id in ACTIVE_BOOKING_STATUSES
            ]

            if active_orders:
                structured_logger.warning(
                    f"Cannot delete product {product_id} - has active orders",
                    user_id=tg_user_id,
                    action="apartment_deletion_blocked",
                    context={
                        'product_id': product_id,
                        'active_orders_count': len(active_orders),
                        'booking_ids': [b.id for b in active_orders]
                    }
                )
                msg = await update.callback_query.message.reply_text(
                    "🚫 На данном товаре есть активные заказы. "
                    "Сообщите администратору об этой ситуации. /help"
                )
                await add_message_to_cleanup(context, msg.chat_id, msg.message_id)
                return VIEW_PRODUCTS

            # Perform soft deletion
            await session.execute(
                sa_update(Product)
                .where(Product.id == product_id)
                .values(
                    is_active=False,
                    updated_at=datetime.utcnow(),
                    updated_by=tg_user_id
                )
            )
            

            structured_logger.info(
                f"Product {product.name} successfully deleted",
                user_id=tg_user_id,
                action="product_deleted",
                context={
                    'product_id': product_id,
                    'deletion_type': 'soft_delete'
                }
            )
            await update.callback_query.message.edit_text("❌ Товар успешно удалён.",
                                                            reply_markup=None)
            await session.commit()
            return VIEW_PRODUCTS
        
#=======Приглашение на дегустацию============
async def honey_invite_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(update,"Введите дату мероприятия (в формате ДД.ММ.ГГГГ):"
    )
    return ASK_DATE

async def honey_invite_ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        event_date = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите дату в виде ДД.ММ.ГГГГ:")
        return ASK_DATE

    context.user_data["event_date"] = event_date
    await update.message.reply_text("Теперь введите время начала (в формате ЧЧ:ММ):")
    return ASK_TIME

# 3️⃣ Получаем время и рассылаем приглашения
async def honey_invite_ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        event_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите время в виде ЧЧ:ММ:")
        return ASK_TIME

    event_date = context.user_data["event_date"]
    event_datetime = datetime.combine(event_date, event_time)

    async with get_async_session() as session:
        # Получаем пользователей
        result = await session.execute(
            select(Session.id,Session.tg_user_id).where(
                Session.role_id == 3,
                Session.sent_message == False
            )
        )
        rows = result.fetchall()

        session_ids = [row.id for row in rows]
        users_to_notify = [row.tg_user_id for row in rows]

        if not users_to_notify:
            await update.message.reply_text("❗ Нет пользователей для рассылки.")
            return ConversationHandler.END

        message_text = (
            f"🍯 <b>Приглашение на дегустацию мёда!</b>\n\n"
            f"Уважаемые гости, приглашаем вас посетить нашу дегустацию мёда "
            f"<b>{event_date.strftime('%d.%m.%Y')}</b> в <b>{event_time.strftime('%H:%M')}</b> "
            f"по адресу: <i>Сочи, Красная Поляна, ул. Плотинная 2</i> 🐝\n\n"
            f"Если вы планируете прийти — напишите «Приду» в чат поддержки /help 💬"
        )

        sent_count = 0
        failed = 0

        # Рассылаем сообщения
        for user_id in users_to_notify:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode="HTML"
                )
                sent_count += 1
            except Exception as e:
                structured_logger.warning(
                    "Failed to send invite",
                    user_id=user_id,
                    action="invite_failed",
                    context={"error": str(e)}
                )
                failed += 1

        # Обновляем статусы в БД
        await session.execute(
            sa_update(Session)
            .where(Session.id.in_(session_ids))
            .values(
                sent_message=True,
                last_action={"event_datetime": event_datetime.isoformat()},
                updated_at=datetime.utcnow()
            )
        )
        await session.commit()

    # Подтверждение админу
    await update.message.reply_text(
        f"✅ Рассылка завершена.\n"
        f"Отправлено: {sent_count}\n"
        f"Ошибок: {failed}",
        reply_markup=ReplyKeyboardRemove()
    )

    structured_logger.info(
        "Honey invite campaign completed",
        action="honey_invite_sent",
        context={
            "sent": sent_count,
            "failed": failed,
            "event_datetime": str(event_datetime)
        }
    )

    return ConversationHandler.END
        
#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END
