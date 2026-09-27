from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardRemove
)
from telegram.ext import (
    ConversationHandler, ContextTypes
)
from utils.logging_config import structured_logger
from db.db_async import get_async_session
from db.models import Product, ProductType
from sqlalchemy import select
from utils.message_tricks import add_message_to_cleanup, cleanup_messages,send_message
from utils.keyboard_builder import get_product_sizes_keyboard, build_order_keyboard
from utils.escape import safe_html
from domain.enums import OrderStatus
from utils.constants import MAX_COMMENT_LENGTH
from services import order_texts
from services.orders import (
    CommentTooLong,
    OrderError,
    QuantityLimit,
    change_quantity,
    create_draft,
    get_customer_draft,
    set_comment,
    transition,
)

from config import get_settings

ADMIN_CHAT_ID = get_settings().admin_chat_id


# Состояния
(
    PRODUCT_TYPES_SELECTION,
    SELECT_SIZE,
    SELECT_QUANTITY,
    CUSTOMER_COMMENT
) = range(4)



async def start_select_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Старт сценария выбора меда — показать все активные типы.
    Поддержка как команды /honey_buy, так и кнопки CallbackQuery.
    """
    # Определяем объект для ответа
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        msg_target = update.callback_query.message
        await query.edit_message_reply_markup(reply_markup=None)
    else:
        msg_target = update.message
    #удаляет предыдущий вариант показа карточек выбранного типа, если гость нажал на Вернуться.
    chat_id = update.effective_chat.id
    msg_ids = context.user_data.get("product_messages", [])
    print(f"DEBUG_delete_MESSAGE_list: {msg_ids}")
    if msg_ids:
        for msg_id in msg_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                print(f"Не удалось удалить сообщение {msg_id}: {e}")
    context.user_data["product_messages"] = []
        # удаляем сообщение с текстом "Отличный выбор! ..."
    last_menu_msg_id = context.user_data.get("last_menu_message_id")
    print(f"DEBUG_delete_GREETINGS: {last_menu_msg_id}")
    if last_menu_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_menu_msg_id)
        except Exception as e:
            print(f"Не удалось удалить сообщение {last_menu_msg_id}: {e}")
        context.user_data["last_menu_message_id"] = None
    # Получаем все активные типы напитков
    async with get_async_session() as session:
        result = await session.execute(
            select(ProductType)
        )
        types = result.scalars().all()

    if not types:
        await msg_target.reply_text("❌ В данный момент нет доступных сортов меда.")
        return ConversationHandler.END

    # Формируем клавиатуру
    keyboard = [[InlineKeyboardButton(t.name, callback_data=f"product_type_{t.id}")] for t in types]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение
    await msg_target.reply_text(
        "Какого мёда желаете сегодня? Выберите сорт:",
        reply_markup=reply_markup
    )

    return PRODUCT_TYPES_SELECTION

async def handle_product_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    type_id = int(query.data.split("_")[-1])
    context.user_data["product_type_id"] = type_id
    print(f"DEBUG_СОРТ: {type_id}")

    async with get_async_session() as session:
        result = await session.execute(
            select(ProductType).where(ProductType.id == type_id)
        )
        product_type = result.scalar_one_or_none()

    type_name = product_type.name if product_type else "Неизвестная категория"

    edited_msg = await query.edit_message_text(
        f"Отличный выбор! Ищем мёд сорта <b>{safe_html(type_name)}</b>:",
        parse_mode="HTML"
    )
    context.user_data["last_menu_message_id"] = edited_msg.message_id

    return await show_filtered_products(update, context)

async def show_filtered_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    type_id = context.user_data.get("product_type_id")

    async with get_async_session() as session:
        result = await session.execute(
        select(Product).where(
        Product.type_id == type_id,
        Product.is_active.is_(True),
        Product.is_draft.is_(False)
        )
    )
        products = result.scalars().all()

    if not products:
        await update.effective_message.reply_text("❌ Похоже, мед этого сорта закончился.")
        return ConversationHandler.END

    context.user_data["product_messages"] = []  # сбрасываем перед показом

    for product in products:
        # Получаем размеры и клавиатуру
        sizes, keyboard_markup, image_file_id = await get_product_sizes_keyboard(product.id)

        caption = f"<b>{safe_html(product.name)}</b>\n{safe_html(product.description) or 'Без описания'}"

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
        context.user_data["product_messages"].append(sent.message_id)
    return SELECT_SIZE


async def handle_size_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data if query else None
        # Парсим индекс из callback_data
    if data:
        try:
            product_size_id = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await query.message.reply_text("Ошибка выбора размера. Попробуйте снова.")
            return PRODUCT_TYPES_SELECTION

        context.user_data["selected_size_id"] = product_size_id
        tg_user_id = update.effective_user.id

        async with get_async_session() as session:
            try:
                # прежние черновики покупателя закрываются: активен только последний
                order = await create_draft(session, tg_user_id, product_size_id)
                context.user_data["session_id"] = order.session_id
                structured_logger.info(
                    "Create order draft",
                    session_id=order.session_id,
                    order_id=order.id,
                    action="order_draft_created",
                )

                keyboard = await build_order_keyboard(order, order.total_price)
                msg = await update.callback_query.message.reply_text(
                    order_texts.draft_card(order), reply_markup=keyboard, parse_mode="HTML"
                )
                await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

                await session.commit()
            except OrderError as e:
                await session.rollback()
                await query.message.reply_text(e.user_message)
                return ConversationHandler.END
            except Exception as e:
                structured_logger.error(
                    f"Error in creation draft order: {str(e)}",
                    user_id=tg_user_id,
                    action="Create order draft",
                    exception=e
                )
                await send_message(update,text=("Ошибка при создании карточки заказа."))
                return ConversationHandler.END

            chat_id = update.effective_chat.id

            for msg_id in context.user_data.get("product_messages", []):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    structured_logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}", user_id=tg_user_id)
            # очищаем список
            context.user_data["product_messages"] = []

            last_menu_msg_id = context.user_data.get("last_menu_message_id")
            if last_menu_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=last_menu_msg_id)
                except Exception as e:
                    structured_logger.debug(f"Не удалось удалить сообщение {last_menu_msg_id}: {e}", user_id=tg_user_id)
            # очищаем список
            context.user_data["last_menu_message_id"] = None
            return SELECT_QUANTITY

async def handle_update_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_user_id = update.effective_user.id
    try:
        _,_, action, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
    except ValueError:
        await query.answer()
        await query.message.reply_text("Ошибка при изменении количества.")
        return SELECT_QUANTITY


    async with get_async_session() as session:

        order = await get_customer_draft(session, order_id, tg_user_id)

        if not order:
            # заказ чужой, уже оформлен или закрыт новым черновиком — старая карточка не должна его менять
            await query.answer("Этот заказ уже оформлен или недоступен.", show_alert=True)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return ConversationHandler.END

        try:
            changed = change_quantity(order, 1 if action == "+" else -1)
        except QuantityLimit as e:
            await query.answer(e.user_message, show_alert=True)
            return SELECT_QUANTITY
        await query.answer()
        if not changed:  # меньше 1 — просто игнорируем
            return SELECT_QUANTITY

        keyboard = await build_order_keyboard(order, order.total_price)
        msg = await query.message.edit_text(order_texts.draft_card(order), reply_markup=keyboard, parse_mode="HTML")
        await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
        order.session.last_action = {"event": "update_quantity", "message_id": query.message.message_id}
        await session.commit()
    return SELECT_QUANTITY

async def customer_comment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашиваем у пользователя комментарий к заказу"""
    query = update.callback_query
    await query.answer()
    try:
        _, _, order_id_str = query.data.split("_")  # customer_comment_<id>
        order_id = int(order_id_str)
    except Exception:
        await query.message.reply_text("Ошибка обработки заказа. Попробуйте снова.")
        return SELECT_QUANTITY

    # Сохраняем order_id в user_data, чтобы поймать в следующем сообщении
    context.user_data["pending_comment_order_id"] = order_id

    await query.message.reply_text(f"✍️ Введите комментарий к заказу (до {MAX_COMMENT_LENGTH} символов):")
    return CUSTOMER_COMMENT  # отдельное состояние

async def save_customer_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняем введённый пользователем комментарий и обновляем карточку заказа"""
    tg_user_id = update.effective_user.id
    order_id = context.user_data.get("pending_comment_order_id")

    if not order_id:
        await update.message.reply_text("Не удалось связать комментарий с заказом.")
        return SELECT_QUANTITY

    comment_text = update.message.text.strip()
    async with get_async_session() as session:
        order = await get_customer_draft(session, order_id, tg_user_id)

        if not order:
            context.user_data.pop("pending_comment_order_id", None)
            await update.message.reply_text("Заказ уже оформлен или не найден.")
            return ConversationHandler.END

        try:
            set_comment(order, comment_text)
        except CommentTooLong as e:
            await update.message.reply_text(e.user_message)
            return CUSTOMER_COMMENT
        await session.commit()

    await cleanup_messages(context)
    structured_logger.info(
        "Customer added comment",
        order_id=order.id,
        action="customer_comment",
        context={"comment_length": len(comment_text)}
    )
    # пересобираем карточку заказа
    keyboard = await build_order_keyboard(order, order.total_price)
    caption = order_texts.draft_card(order)

    # находим последнее сообщение с карточкой заказа
    last_msg_id = context.user_data.get("last_order_message_id")
    chat_id = update.effective_chat.id

    if last_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            structured_logger.debug(f"Не удалось обновить карточку заказа {last_msg_id}: {e}", user_id=tg_user_id)
            # если не нашли старое сообщение — просто шлём новое
            msg = await update.message.reply_text(caption, reply_markup=keyboard, parse_mode="HTML")
            context.user_data["last_order_message_id"] = msg.message_id
    else:
        # первый раз сохраняем ID карточки
        msg = await update.message.reply_text(caption, reply_markup=keyboard, parse_mode="HTML")
        context.user_data["last_order_message_id"] = msg.message_id

    # убираем флаг pending_comment
    context.user_data.pop("pending_comment_order_id", None)

    return SELECT_QUANTITY

async def proceed_new_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывается при нажатии кнопки 'Оплатить'"""
    query = update.callback_query
    tg_user_id = update.effective_user.id

    try:
        _, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
        async with get_async_session() as session:
            # Достаём заказ с деталями; повторный клик по «Заказать» не должен создавать второй заказ
            order = await get_customer_draft(session, order_id, tg_user_id)
            if not order:
                await query.answer("Этот заказ уже оформлен.", show_alert=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                return ConversationHandler.END

            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)
            transition(order, OrderStatus.CREATED)

            # Сообщение для менеджеров
            manager_text = order_texts.manager_card(order, f"🔔 Новый заказ #{order.id}🔔")

            # Кнопки
            buttons = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_order_{order.id}"),
                InlineKeyboardButton("Отклонить ❌", callback_data=f"decline_order_{order.id}")]
            ]
            markup = InlineKeyboardMarkup(buttons)
            await session.commit()
            # Уведомляем клиента
            msg = await send_message(update,
                text="✅ Ваш заказ создан! Ожидайте уведомление от продавца.",
                reply_markup=ReplyKeyboardRemove()
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

            # Сообщение в чат менеджеров
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=manager_text,
                reply_markup=markup,
                parse_mode='HTML'
            )
            structured_logger.info(
                "new order",
                user_id = order.tg_user_id,
                order_id = order.id,
                action = "order_created",
                context = {'item':order.product_size.product.name,
                           'size': order.product_size.sizes.name,
                           'qty': order.product_count,
                           'amount': order.total_price}
            )

    except Exception as e:
        structured_logger.error(
            f"Error in sending order nitification: {str(e)}",
            user_id = tg_user_id,
            action="Send new order notification",
            exception=e,
            context={'admin_chat_id': ADMIN_CHAT_ID}
        )
        await send_message(update,text=("Ошибка при отправке уведомления продавцу."))

        
    return ConversationHandler.END

# === Отмена ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена поиска"""
    context.user_data.clear()
    await update.message.reply_text("❌ Заказ меда отменен",reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END
