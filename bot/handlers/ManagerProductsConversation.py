"""«Мой мёд»: товары магазина менеджера — цены по размерам и снятие с продажи."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from db.db_async import get_async_session
from handlers.RegistrationConversation import route_after_login
from services import catalog
from utils.access import get_actor, manager_only
from utils.constants import MAX_PRICE
from utils.escape import safe_html
from utils.logging_config import structured_logger
from utils.manager_lk_collection import fetch_seller_products, get_manager_product_sizes_keyboard
from utils.message_tricks import add_message_to_cleanup, cleanup_messages, send_message
from utils.telegram_media import send_card
from utils.validation import parse_price

(VIEW_PRODUCTS,
EDIT_PRICE_PROMPT,
EDIT_PRICE_WAIT_INPUT) = range(3)

NO_ACCESS_TEXT = "🚫 Товар не найден или принадлежит другому магазину."


@manager_only
async def handle_manager_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is not None:
        await query.answer()

    actor = await get_actor(update)
    try:
        # менеджер видит товары своего магазина, владелец платформы — всех магазинов
        products = await fetch_seller_products(actor.shop_scope)
        if not products:
            await update.effective_chat.send_message("❌ Ваших товаров не найдено в базе.")
            return ConversationHandler.END

        for product in products:
            # Получаем размеры и клавиатуру
            _, keyboard_markup, cover = await get_manager_product_sizes_keyboard(product.id)
            caption = (f"<b>{safe_html(product.name)}</b> ||сорт: {safe_html(product.product_type.name)}\n"
                       f"{safe_html(product.description) or 'Без описания'}")
            sent = await send_card(update.effective_chat, cover, caption, reply_markup=keyboard_markup)
            await add_message_to_cleanup(context, sent.chat_id, sent.message_id)
        return VIEW_PRODUCTS

    except Exception as e:
        structured_logger.error(
            f"Error in manager products: {str(e)}", user_id=actor.user_id, action="view_manager_products", exception=e
        )
        await send_message(update, text="Ошибка при демонстрации товаров.")
        return ConversationHandler.END


#======редактирование карточки товара=========
async def handle_product_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    actor = await get_actor(update)
    productsize_id = int(query.data.split("_")[-1])

    async with get_async_session() as session:
        # чужой магазин — как будто товара нет
        productsize = await catalog.get_offer(session, productsize_id, actor.shop_scope)
    if productsize is None:
        structured_logger.warning(
            "Product size not found or out of shop scope", user_id=actor.user_id,
            action="product_price_edit_denied", context={"productsize_id": productsize_id},
        )
        await send_message(update, NO_ACCESS_TEXT)
        return VIEW_PRODUCTS

    # Сохраняем id товара для последующих шагов
    context.user_data["edit_productsize_id"] = productsize_id
    context.user_data["sizename"] = str(productsize.sizes.name)
    text = (
        f"🛠 Вы можете отредактировать только <b>стоимость</b> товара.\n\n"
        f"💰 Текущая цена: <b>{productsize.price} ₽/{productsize.sizes.name}кг</b>\n\n"
        f"Выберите действие:"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_price_start"),
        InlineKeyboardButton("🔙 Вернуться назад", callback_data="honey_get"),
    ]])
    msg = await send_message(update, text, reply_markup=keyboard, parse_mode="HTML")
    await add_message_to_cleanup(context, msg.chat_id, msg.message_id)
    return EDIT_PRICE_PROMPT


async def handle_edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💬 Введите новую стоимость в рублях (только число):", reply_markup=None)
    return EDIT_PRICE_WAIT_INPUT


async def handle_new_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = await get_actor(update)
    new_price_text = update.message.text.strip()
    productsize_id = context.user_data.get("edit_productsize_id")
    sizename = context.user_data.get("sizename")

    new_price = parse_price(new_price_text)
    if new_price is None:
        structured_logger.warning(
            "Invalid price input.", user_id=actor.user_id, action="invalid_price_input",
            context={'input_value': new_price_text[:50]},
        )
        await update.message.reply_text(f"❌ Введите цену числом от 1 до {MAX_PRICE} ₽.")
        return EDIT_PRICE_WAIT_INPUT

    async with get_async_session() as session:
        result = await catalog.update_price(session, productsize_id, new_price, actor.shop_scope, actor.user_id)
        if result is None:
            await update.message.reply_text(NO_ACCESS_TEXT)
            return ConversationHandler.END
        await session.commit()
    offer, old_price = result

    structured_logger.info(
        f"Product price updated from {old_price} to {new_price}",
        user_id=actor.user_id,
        action="product_price_updated",
        context={'productsize_id': offer.id, 'old_price': old_price, 'new_price': new_price},
    )
    await update.message.reply_text(f"✅ Стоимость обновлена: <b>{new_price:.0f} ₽/{sizename}кг</b>", parse_mode="HTML")

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
    await update.effective_chat.send_message(
        f"Вы уверены, что хотите удалить товар №{product_id}?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Удалить", callback_data=f"delete_confirm_{product_id}"),
            InlineKeyboardButton("↩️ Отмена", callback_data="delete_cancel"),
        ]]),
    )
    return VIEW_PRODUCTS


#=======подтверждение получено ==========
async def delete_product_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    actor = await get_actor(update)
    product_id = int(query.data.split("_")[-1])

    async with get_async_session() as session:
        result, active_orders = await catalog.withdraw(session, product_id, actor.shop_scope, actor.user_id)
        await session.commit()

    if result is catalog.WithdrawResult.NOT_FOUND:
        await update.effective_chat.send_message(NO_ACCESS_TEXT)
        return VIEW_PRODUCTS
    if result is catalog.WithdrawResult.HAS_ACTIVE_ORDERS:
        structured_logger.warning(
            f"Cannot withdraw product {product_id} - has active orders",
            user_id=actor.user_id,
            action="product_withdraw_blocked",
            context={'product_id': product_id, 'order_ids': active_orders},
        )
        msg = await update.effective_chat.send_message(
            "🚫 На данном товаре есть активные заказы. "
            "Сообщите администратору об этой ситуации. /help"
        )
        await add_message_to_cleanup(context, msg.chat_id, msg.message_id)
        return VIEW_PRODUCTS

    structured_logger.info(
        "Product withdrawn from sale", user_id=actor.user_id, action="product_withdrawn",
        context={'product_id': product_id},
    )
    await query.edit_message_text("❌ Товар успешно удалён.", reply_markup=None)
    return VIEW_PRODUCTS


#=========конец диалога=============
async def end_and_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и возвращает в меню."""
    await cleanup_messages(context)
    await route_after_login(update, context)
    return ConversationHandler.END
