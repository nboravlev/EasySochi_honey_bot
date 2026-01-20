from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
    Update, ReplyKeyboardRemove
)
from telegram.ext import (
    ConversationHandler, CallbackQueryHandler, CommandHandler,
    MessageHandler, filters, ContextTypes
)
from sqlalchemy.orm import selectinload
from utils.logging_config import LoggingContext, structured_logger, log_db_select
from db.db_async import get_async_session
from db.models import Product, ProductType, ProductSize, Size, Order, OrderPackage, Package, Session
from sqlalchemy import select
from datetime import datetime
from utils.message_tricks import add_message_to_cleanup, cleanup_messages,send_message
from utils.keyboard_builder import get_product_sizes_keyboard, build_order_keyboard
from utils.user_session_lastorder import get_actual_session_by_tg_id
from datetime import timedelta

import os

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not (ADMIN_CHAT_ID):
    raise RuntimeError("Admin chat id did not set in environment variables")


# Состояния
(
    PRODUCT_TYPES_SELECTION,
    SELECT_SIZE,
    SELECT_QUANTITY,
    CUSTOMER_COMMENT
) = range(4)



ORDER_STATUS_CREATED = 1
ORDER_STATUS_CUSTOMER_INFORMED = 2
ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_READY = 4
ORDER_STATUS_RECEIVED = 5
ORDER_STATUS_DECLINED = 6
ORDER_STATUS_EXPIRED = 7
ORDER_STATUS_DRAFT = 8


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
        f"Отличный выбор! Ищем мёд сорта <b>{type_name}</b>:",
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

        caption = f"<b>{product.name}</b>\n{product.description or 'Без описания'}"

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
    print(f"DEBUG_размер_имеем_{data}")
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
                new_session = Session(tg_user_id=tg_user_id, role_id = 2,last_action={"event": "order_started"})
                session.add(new_session)
                await session.flush()  # получаем id новой сессии
                session_id = new_session.id

                context.user_data["session_id"] = session_id  # кладём обратно в контекст

                structured_logger.info(
                "Create buyer session",
                user_id=tg_user_id,
                session_id = session_id,
                action="create_buyer_session"
                )
            except Exception as e:
                structured_logger.error(
                    f"Error in sigh up for tasting: {str(e)}",
                    user_id=tg_user_id,
                    action="create_buyer_session",
                    exception=e
                )
                await send_message(update,text=("Ошибка при начале новой сессии."))
                return ConversationHandler.END 
            try:
                # получаем размер напитка вместе с его Drink и Size
                result = await session.execute(
                    select(ProductSize)
                    .options(
                        selectinload(ProductSize.product),
                        selectinload(ProductSize.sizes).selectinload(Size.package),
                    )
                    .where(ProductSize.id == product_size_id)
                )
                product_size = result.scalar_one()

                # создаём заказ (draft)
                order = Order(
                    tg_user_id=tg_user_id,
                    product_size_id=product_size.id,
                    status_id= ORDER_STATUS_DRAFT,
                    product_count=1,
                    total_price=product_size.price,
                    session_id = session_id if session_id else 1
                )
                session.add(order)
                await session.flush()  # чтобы получить order.id
                
                structured_logger.info(
                "Create order draft",
                user_id=tg_user_id,
                order_id = order.id,
                action="Create order draft"
                )

                keyboard = await build_order_keyboard(order, order.total_price)

                caption = f"<b>{product_size.product.name}</b>\n" \
                        f"🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝\n" \
                        f"Цена ({product_size.sizes.name}кг) – {int(product_size.price)}₽\n" \
                        f"Количество: 1\n" \
                        f"Тара: {product_size.sizes.package.name}\n"\
                        f"Комментарий: -"

                msg = await update.callback_query.message.reply_text(
                    caption, reply_markup=keyboard, parse_mode="HTML"
                )
                await add_message_to_cleanup(context,msg.chat_id,msg.message_id)

                await session.commit()
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
                    print(f"Не удалось удалить сообщение {msg_id}: {e}")
            # очищаем список
            context.user_data["product_messages"] = []

            last_menu_msg_id = context.user_data.get("last_menu_message_id")
            if last_menu_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=last_menu_msg_id)
                except Exception as e:
                    print(f"Не удалось удалить сообщение {last_menu_msg_id}: {e}")
            # очищаем список
            context.user_data["last_menu_message_id"] = None
            return SELECT_QUANTITY
        
async def handle_update_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    print(f"DEBUG_quantity_data: {query.data.split("_")}")
    try:
        _,_, action, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
    except ValueError:
        await query.message.reply_text("Ошибка при изменении количества.")
        return SELECT_QUANTITY
    

    async with get_async_session() as session:

        result = await session.execute(
            select(Order)
            .options(
                selectinload(Order.product_size).selectinload(ProductSize.product),  
                selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
                selectinload(Order.session)
            )
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()

        if not order:
            await query.message.edit_text("Заказ не найден. Начните сначала.")
            return ConversationHandler.END


        # изменение, не допускать меньше 1
        if action == "+":
            order.product_count += 1
        elif action == "-" and order.product_count > 1:
            order.product_count -= 1
        else:
            # если попытка уменьшить ниже 1 — просто игнорируем
            structured_logger.debug("Attempt to decrease below 1 ignored")

           
        # пересчёт цены: напиток + добавки

        order.total_price = order.product_size.price * order.product_count 
        await session.flush()

        # пересобираем клавиатуру

        keyboard = await build_order_keyboard(order, order.total_price)

        caption = f"<b>{order.product_size.product.name}</b>\n" \
                f"🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝\n" \
                f"Цена ({order.product_size.sizes.name}кг) – {int(order.product_size.price)}₽\n" \
                f"Количество: {order.product_count}\n" \
                f"Тара: {order.product_size.sizes.package.name}\n" \
                f"Комментарий: {order.customer_comment or '-'}"

        msg = await query.message.edit_text(caption, reply_markup=keyboard, parse_mode="HTML")
        await add_message_to_cleanup(context,msg.chat_id,msg.message_id)
        session_obj = await session.get(Session, order.session_id)
        if session_obj:
            session_obj.last_action = {
                "event": "update_quantity",
                "message_id": query.message.message_id
            }
        await session.commit()
    return SELECT_QUANTITY

async def customer_comment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашиваем у пользователя комментарий к заказу"""
    query = update.callback_query
    await query.answer()
    print(f"DEBUG_customer_commment: {query.data.split("_")}")
    try:
        _, _, order_id_str = query.data.split("_")  # customer_comment_<id>
        order_id = int(order_id_str)
    except Exception:
        await query.message.reply_text("Ошибка обработки заказа. Попробуйте снова.")
        return SELECT_QUANTITY

    # Сохраняем order_id в user_data, чтобы поймать в следующем сообщении
    context.user_data["pending_comment_order_id"] = order_id

    await query.message.reply_text("✍️ Введите комментарий к заказу:")
    return CUSTOMER_COMMENT  # отдельное состояние

async def save_customer_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняем введённый пользователем комментарий и обновляем карточку заказа"""
    tg_user_id = update.effective_user.id
    order_id = context.user_data.get("pending_comment_order_id")

    if not order_id:
        await update.message.reply_text("Не удалось связать комментарий с заказом.")
        return SELECT_QUANTITY

    comment_text = update.message.text.strip()
    await cleanup_messages(context)
    async with get_async_session() as session:
        result = await session.execute(
            select(Order)
            .options(
                selectinload(Order.product_size).selectinload(ProductSize.product),
                selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
            )
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()

        if not order:
            await update.message.reply_text("Заказ не найден.")
            return SELECT_QUANTITY

        # сохраняем комментарий
        order.customer_comment = comment_text
        await session.commit()

        structured_logger.info(
            "Customer added comment",
            user_id=tg_user_id,
            order_id=order.id,
            comment=comment_text,
            action="customer_comment"
        )

        # пересобираем клавиатуру заказа
        keyboard = await build_order_keyboard(order, order.total_price)

        caption = (
            f"<b>{order.product_size.product.name}</b>\n"
            f"🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝👨‍🌾🍯🐝\n"
            f"Цена ({order.product_size.sizes.name}кг) – {int(order.product_size.price)}₽\n"
            f"Количество: {order.product_count}\n"
            f"Тара: {order.product_size.sizes.package.name}\n"
            f"Комментарий: {order.customer_comment or '-'}"
        )

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
            print(f"Не удалось обновить карточку заказа {last_msg_id}: {e}")
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
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    try:
        _, order_id_str = query.data.split("_")
        order_id = int(order_id_str)
        async with get_async_session() as session:
                # Достаём заказ с деталями
            result = await session.execute(
                select(Order)
                .options(
                    selectinload(Order.product_size).selectinload(ProductSize.product),
                    selectinload(Order.product_size).selectinload(ProductSize.sizes).selectinload(Size.package),
                    selectinload(Order.user)
                )
                .where(Order.id == order_id)
            )
            order = result.scalars().first()
            order.status_id = ORDER_STATUS_CREATED

            # Сообщение для менеджеров
            created_local = order.created_at + timedelta(hours=3)
                
            manager_text = (
                f"🔔 Новый заказ #{order.id}🔔\n\n"
                f"🍯: <b>{order.product_size.product.name}</b>\n"
                f"🫙 Размер: {order.product_size.sizes.name}кг\n"
                f"🔢 Количество: {order.product_count}\n"
                f"💰 Стоимость: {order.total_price} ₽\n"
                f"⏰ Создан: {created_local.strftime('%H:%M %d.%m.%Y')}\n"
                f"💬 Комментарий клиента: {order.customer_comment or '—'}\n"
                f"👨: {order.user.firstname or order.user.username}\n"
                f"☎️ Номер: {order.user.phone_number or 'не указан'}"
            )

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
                context = {'item':order.product_size.product.name,
                           'size': order.product_size.sizes.name,
                           'qty': order.product_count,
                           'amount': order.total_price}
            )
            session.commit()

    except Exception as e:
        structured_logger.error(
            f"Error in sending order nitification: {str(e)}",
            user_id = ADMIN_CHAT_ID,
            action="Send new order notification",
            exception=e
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
