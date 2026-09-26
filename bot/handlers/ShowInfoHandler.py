from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes





INFO_TEXTS = {
    "info_booking": {
        "title": "🍯 *Инструкция по заказу:*",
        "body": (
            "1. Нажмите /start и пройдите короткую регистрацию;\n"
            "2. Рекомендуется оставить номер телефона для лучшей коммуникации;\n"
            "3. Время проведения дегустации известно за несколько дней\n"
            "4. Если вы запишитесь, то робот пришлет вам уведомление\n"
            "5. Мед продается в таре по 0.5, 1 и 1.5 кг \n"
            "6. Для заказа меда нужно выбрать сорт и размер\n"
            "7. В карточке заказа нажмите ➕,\n"
            "если хотите 2 или более банки этого сорта\n"
            "8. Нажмите на Комментарий к заказу если хотите написать продавцу\n"
            "9. При нажатии на кнопку Заказать формируется заказ\n"
            "10. Когда продавец подтвердит ваш заказ, вам придет уведомление\n"
            "11. В уведомлении нажмите на кнопку Сегодня/Завтра или Позже,\n"
            "чтобы проинформировать продавца, когда примерно вы придете за мёдом.\n"
            "12. Если возникнут сложности, напишите в раздел 'Помощь'."
        )
    },
    "info_object": {
        "title": "🧾 *Правила сервиса*",
        "body": (
            "1. EasySochi является информационным сервисом (чат-ботом) и не является стороной сделок покупки.\n"
            "2. Сервис предоставляет платформу для коммуникации между продавцом и покупателем.\n"
            "3. Ответственность за достоверность информации (описания, фото, цены) несёт лицо, её разместившее.\n"
            "4. Все договорённости о покупке заключаются напрямую между собственником и пользователем.\n"
            "5. EasySochi не контролирует и не гарантирует выполнение обязательств сторон.\n"
            "6. Сервис стремится обеспечивать бесперебойную работу чат-бота, но не несёт ответственности за перебои связи или недоступность Telegram.\n"
            "7. Пользователи предоставляют свои персональные данные добровольно.\n"
            "8. Обработка данных осуществляется только в объёме, необходимом для работы сервиса (регистрация, поиск, заказ, уведомления).\n"
            "9. EasySochi обязуется не передавать данные третьим лицам, кроме случаев, предусмотренных законом.\n"
            "10. Используя сервис, пользователь подтверждает, что ознакомлен с данными условиями и принимает их.\n"
        )
    }
}


def _get_effective_message(update: Update):
    """
    Возвращает message-объект, независимо от того, пришло ли это update.message
    или это callback_query (update.callback_query.message).
    """
    if update.message:
        return update.message
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает меню справки. Работает как при прямом вызове /info, так и при callback.
    """
    message = _get_effective_message(update)
    if not message:
        return

    keyboard = [
        [InlineKeyboardButton("📌 Инструкция", callback_data="info_booking"),
        InlineKeyboardButton("Правила и условия🖋", callback_data="info_object")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("ℹ️ Выберите инструкцию:", reply_markup=reply_markup)


async def show_info_text(update_or_query: Update, key: str):
    """
    Выводит справочный текст по ключу. Работает и для обычных сообщений, и для callback.
    Кнопка 'Назад в инфо' имеет callback_data='help_menu'.
    """
    data = INFO_TEXTS.get(key)
    if not data:
        return

    text = f"{data['title']}\n\n{data['body']}"
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад в инфо", callback_data="info_menu")]]
    )

    message = _get_effective_message(update_or_query)
    if not message:
        return

    # Можно использовать edit_message_text если вы хотите заменить предыдущую карточку,
    # но reply_text достаточно универсален.
    await message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def info_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик callback'ов для help_*
    - отвечает на query (query.answer())
    - вызывает show_help_text или возвращает в меню вызовом help_command
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()  # убираем "крутилку" в UI

    data = query.data or ""
    if data == "info_booking":
        await show_info_text(update, "info_booking")
    elif data == "info_object":
        await show_info_text(update, "info_object")
    elif data == "info_menu":
        await info_command(update, context)
    else:
        return