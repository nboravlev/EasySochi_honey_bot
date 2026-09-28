from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardRemove
)
from telegram.ext import (
    ConversationHandler, ContextTypes
)
from utils.logging_config import structured_logger
from db.db_async import get_async_session
from utils.message_tricks import add_message_to_cleanup, cleanup_messages,send_message
from utils.keyboard_builder import get_product_sizes_keyboard, build_order_keyboard
from utils.escape import safe_html
from domain.enums import OrderStatus
from domain.messages import Button, OutMessage, ToShopStaff
from utils.constants import MAX_COMMENT_LENGTH
from services import catalog, notifications, order_texts, shops
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
from utils.access import user_id_for_telegram
from utils.telegram_delivery import deliver, log_no_channel
from utils.telegram_media import send_card

NOT_REGISTERED_TEXT = "Чтобы оформить заказ, сначала пройдите короткую регистрацию: /start"


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
        await query.edit_message_reply_markup(reply_markup=None)
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
    # Сорта, в которых есть товары на витрине (или во всех магазинах — в режиме общего каталога)
    async with get_async_session() as session:
        types = await catalog.product_types(session, await shops.storefront_shop_id(session))

    if not types:
        await update.effective_chat.send_message("❌ В данный момент нет доступных сортов меда.")
        return ConversationHandler.END

    # Формируем клавиатуру
    keyboard = [[InlineKeyboardButton(t.name, callback_data=f"product_type_{t.id}")] for t in types]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение
    await update.effective_chat.send_message(
        "Какого мёда желаете сегодня? Выберите сорт:",
        reply_markup=reply_markup
    )

    return PRODUCT_TYPES_SELECTION

async def handle_product_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    type_id = int(query.data.split("_")[-1])
    context.user_data["product_type_id"] = type_id
    async with get_async_session() as session:
        product_type = await catalog.get_type(session, type_id)

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
        products = await catalog.products_of_type(session, type_id, await shops.storefront_shop_id(session))

    if not products:
        await update.effective_chat.send_message("❌ Похоже, мед этого сорта закончился.")
        return ConversationHandler.END

    context.user_data["product_messages"] = []  # сбрасываем перед показом

    for product in products:
        # Получаем размеры и клавиатуру
        sizes, keyboard_markup, cover = await get_product_sizes_keyboard(product.id)

        caption = f"<b>{safe_html(product.name)}</b>\n{safe_html(product.description) or 'Без описания'}"
        sent = await send_card(update.effective_chat, cover, caption, reply_markup=keyboard_markup)
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
            await update.effective_chat.send_message("Ошибка выбора размера. Попробуйте снова.")
            return PRODUCT_TYPES_SELECTION

        context.user_data["selected_size_id"] = product_size_id
        customer_id = await user_id_for_telegram(update.effective_user.id)
        if customer_id is None:
            await update.effective_chat.send_message(NOT_REGISTERED_TEXT)
            return ConversationHandler.END

        async with get_async_session() as session:
            try:
                # прежние черновики покупателя закрываются: активен только последний
                order = await create_draft(session, customer_id, product_size_id)
                context.user_data["session_id"] = order.session_id
                structured_logger.info(
                    "Create order draft",
                    session_id=order.session_id,
                    order_id=order.id,
                    action="order_draft_created",
                )

                keyboard = await build_order_keyboard(order, order.total_price)
                msg = await update.effective_chat.send_message(
                    order_texts.draft_card(order), reply_markup=keyboard, parse_mode="HTML"
                )
                await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

                await session.commit()
            except OrderError as e:
                await session.rollback()
                await update.effective_chat.send_message(e.user_message)
                return ConversationHandler.END
            except Exception as e:
                structured_logger.error(
                    f"Error in creation draft order: {str(e)}",
                    user_id=customer_id,
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
                    structured_logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}", user_id=customer_id)
            # очищаем список
            context.user_data["product_messages"] = []

            last_menu_msg_id = context.user_data.get("last_menu_message_id")
            if last_menu_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=last_menu_msg_id)
                except Exception as e:
                    structured_logger.debug(f"Не удалось удалить сообщение {last_menu_msg_id}: {e}", user_id=customer_id)
            # очищаем список
            context.user_data["last_menu_message_id"] = None
            return SELECT_QUANTITY

async def handle_update_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    customer_id = await user_id_for_telegram(update.effective_user.id)
    try:
        _,_, action, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
    except ValueError:
        await query.answer()
        await update.effective_chat.send_message("Ошибка при изменении количества.")
        return SELECT_QUANTITY


    async with get_async_session() as session:

        order = await get_customer_draft(session, order_id, customer_id)

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
        msg = await query.edit_message_text(order_texts.draft_card(order), reply_markup=keyboard, parse_mode="HTML")
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
        await update.effective_chat.send_message("Ошибка обработки заказа. Попробуйте снова.")
        return SELECT_QUANTITY

    # Сохраняем order_id в user_data, чтобы поймать в следующем сообщении
    context.user_data["pending_comment_order_id"] = order_id

    await update.effective_chat.send_message(f"✍️ Введите комментарий к заказу (до {MAX_COMMENT_LENGTH} символов):")
    return CUSTOMER_COMMENT  # отдельное состояние

async def save_customer_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняем введённый пользователем комментарий и обновляем карточку заказа"""
    customer_id = await user_id_for_telegram(update.effective_user.id)
    order_id = context.user_data.get("pending_comment_order_id")

    if not order_id:
        await update.message.reply_text("Не удалось связать комментарий с заказом.")
        return SELECT_QUANTITY

    comment_text = update.message.text.strip()
    async with get_async_session() as session:
        order = await get_customer_draft(session, order_id, customer_id)

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
            structured_logger.debug(f"Не удалось обновить карточку заказа {last_msg_id}: {e}", user_id=customer_id)
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
    customer_id = await user_id_for_telegram(update.effective_user.id)

    try:
        _, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
        async with get_async_session() as session:
            # Достаём заказ с деталями; повторный клик по «Заказать» не должен создавать второй заказ
            order = await get_customer_draft(session, order_id, customer_id)
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

            # карточка — в служебный чат магазина, которому принадлежит товар; в очередь вместе с заказом
            manager_message = OutMessage(
                order_texts.manager_card(order, f"🔔 Новый заказ #{order.id}🔔"),
                [[Button("✅ Подтвердить", action=f"confirm_order_{order.id}"),
                  Button("Отклонить ❌", action=f"decline_order_{order.id}")]],
            )
            pending = notifications.ids_of(
                await notifications.enqueue(session, ToShopStaff(order.shop_id), manager_message, "order_created")
            )
            await session.commit()
            # Уведомляем клиента
            msg = await send_message(update,
                text="✅ Ваш заказ создан! Ожидайте уведомление от продавца.",
                reply_markup=ReplyKeyboardRemove()
            )
            await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

            if not pending:
                log_no_channel(ToShopStaff(order.shop_id), "order_created")
            await deliver(context.bot, pending)
            structured_logger.info(
                "new order",
                user_id = order.customer_id,
                order_id = order.id,
                action = "order_created",
                context = {'item':order.product_size.product.name,
                           'size': order.product_size.sizes.name,
                           'qty': order.product_count,
                           'amount': order.total_price,
                           'shop_id': order.shop_id}
            )

    except Exception as e:
        structured_logger.error(
            f"Error in sending order nitification: {str(e)}",
            user_id = customer_id,
            action="Send new order notification",
            exception=e,
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
