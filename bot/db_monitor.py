import os
from sqlalchemy import text
import asyncio
from db.db_async import get_async_session





# Конфигурация

CHAT_ID = -1002843679066  # канал или чат

async def check_db(context):
    bot = context.bot

    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        status_ok = True

    except Exception as e:
        status_ok = False


    # ВСЕГДА отправляем статус, без проверки на изменение
    text_msg = (
        "🐝 <b>База данных honeybot доступна</b>"
        if status_ok
        else "❄️ <b>База данных honeybot недоступна!</b>"
    )
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text_msg, parse_mode="HTML")
    except Exception as send_error:
        pass

