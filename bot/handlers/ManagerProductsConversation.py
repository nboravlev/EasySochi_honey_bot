from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
    )
from telegram.ext import (
    ContextTypes, 
    ConversationHandler
)
from db.db_async import get_async_session
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import selectinload
from domain.order_flow import ACTIVE_STATUSES
from utils.timeutils import utcnow
from handlers.RegistrationConversation import route_after_login

from utils.manager_lk_collection import fetch_seller_products, get_manager_product_sizes_keyboard
from utils.message_tricks import send_message, add_message_to_cleanup, cleanup_messages

from utils.logging_config import structured_logger

from db.models import ProductSize,Product

from utils.access import manager_only, is_owner
from utils.escape import safe_html
from utils.validation import parse_price
from utils.constants import MAX_PRICE


(VIEW_PRODUCTS,
EDIT_PRICE_PROMPT,
EDIT_PRICE_WAIT_INPUT) = range(3)




@manager_only
async def handle_manager_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = getattr(update, "callback_query", None)

    # Определяем, откуда вызвали
    is_callback = query is not None
    if is_callback:
        await query.answer()
        
    try:
        tg_user_id = update.effective_user.id
        is_admin = is_owner(tg_user_id)
        products = await fetch_seller_products(tg_user_id,is_admin)

        if not products:
            await update.effective_chat.send_message("❌ Ваших товаров не найдено в базе.")
            return ConversationHandler.END

        for product in products:
            # Получаем размеры и клавиатуру
            sizes, keyboard_markup, image_file_id = await get_manager_product_sizes_keyboard(product.id)

            caption = (f"<b>{safe_html(product.name)}</b> ||сорт: {safe_html(product.product_type.name)}\n"
                       f"{safe_html(product.description) or 'Без описания'}")

            if image_file_id:
                sent = await update.effective_chat.send_photo(
                    photo=image_file_id,
                    caption=caption,
                    reply_markup=keyboard_markup,
                    parse_mode="HTML"
                )
            else:
                sent = await update.effective_chat.send_message(
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

    async with get_async_session() as session:
        result = await session.execute(
            select(ProductSize).options(selectinload(ProductSize.product),
                                        selectinload(ProductSize.sizes))
                            .where(ProductSize.id == productsize_id)
        )
        productsize = result.scalar_one_or_none()

        if not productsize:
            structured_logger.warning(
                f"Product size {productsize_id} not found for upgrade.",
                user_id=tg_user_id,
                action="productsize_upgrade_not_found",
                context={'productsize_id': productsize_id}
            )
            await send_message(update, "❌ Товар не найден.")
            return VIEW_PRODUCTS

        if productsize.product.created_by != tg_user_id and not is_owner(tg_user_id):
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

    await query.edit_message_text(
        "💬 Введите новую стоимость в рублях (только число):",
        reply_markup=None
    )
    return EDIT_PRICE_WAIT_INPUT

async def handle_new_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user_id = update.effective_user.id
    new_price_text = update.message.text.strip()
    productsize_id = context.user_data.get("edit_productsize_id")
    sizename = context.user_data.get("sizename")

    new_price = parse_price(new_price_text)
    if new_price is None:
        structured_logger.warning(
            "Invalid price input.",
            user_id=tg_user_id,
            action="invalid_price_input",
            context={'input_value': new_price_text[:50]}
        )
        await update.message.reply_text(f"❌ Введите цену числом от 1 до {MAX_PRICE} ₽.")
        return EDIT_PRICE_WAIT_INPUT

    async with get_async_session() as session:
        result = await session.execute(
            select(ProductSize).options(selectinload(ProductSize.product))
            .where(ProductSize.id == productsize_id)
        )
        productsize = result.scalar_one_or_none()

        if not productsize:
            await update.message.reply_text("⚠️ Объект не найден.")
            return VIEW_PRODUCTS
        if productsize.product.created_by != tg_user_id and not is_owner(tg_user_id):
            await update.message.reply_text("🚫 У вас нет прав для редактирования этого товара.")
            return ConversationHandler.END

        # Обновляем цену
        old_price = productsize.price
        productsize.price = new_price
        productsize.updated_at = utcnow()
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
    
    await update.effective_chat.send_message(
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

    # незавершённые заказы мешают снять товар с продажи
    
        
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
            await update.effective_chat.send_message("❌ Товар не найден.")
            return VIEW_PRODUCTS

        # снять с продажи можно только свой товар (владелец — любой)
        if product.created_by != tg_user_id and not is_owner(tg_user_id):
            structured_logger.warning(
                f"Unauthorized delete attempt by user {tg_user_id}",
                user_id=tg_user_id,
                action="unauthorized_product_delete_attempt",
                context={'product_id': product_id}
            )
            await update.effective_chat.send_message("🚫 У вас нет прав снимать этот товар с продажи.")
            return VIEW_PRODUCTS

        # Собираем все активные заказы через вложенные циклы
        active_orders = [
            order
            for size in product.product_sizes
            for order in size.orders
            if order.status_id in ACTIVE_STATUSES
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
            msg = await update.effective_chat.send_message(
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
                updated_at=utcnow(),
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
        await update.callback_query.edit_message_text("❌ Товар успешно удалён.",
                                                        reply_markup=None)
        await session.commit()
        return VIEW_PRODUCTS
        
#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END
