"""Фото товаров в Telegram: приём от менеджера, отправка карточек, перенос старых фото в хранилище.

Источник истины — файл в хранилище (services.media). Telegram file_id — кэш: отправляем по нему,
а если его нет или Telegram его не принимает (например, сменился токен бота) — загружаем файл
и запоминаем новый file_id.
"""
import asyncio

from telegram import Bot, Chat, InputFile, Message
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from db.db_async import get_async_session
from services import catalog, media
from services.catalog import Photo
from utils.logging_config import structured_logger

BACKFILL_BATCH = 20


async def download(bot: Bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    return bytes(await tg_file.download_as_bytearray())


def _input_file(photo: Photo) -> InputFile | None:
    if photo.storage_key and media.storage().exists(photo.storage_key):
        return InputFile(media.storage().read(photo.storage_key), filename="photo.jpg")
    return None


async def accept_photo(bot: Bot, chat: Chat, file_id: str) -> Photo:
    """Фото от менеджера: квадрат по центру → хранилище → превью в чат (его file_id — кэш).

    Если хранилище недоступно (том не смонтирован, нет прав) — фото всё равно принимается,
    но только как file_id Telegram; ошибка пишется в лог.
    """
    processed = await asyncio.to_thread(media.square_jpeg, await download(bot, file_id))
    key = None
    try:
        key = await asyncio.to_thread(media.storage().save, processed, media.PRODUCTS)
    except OSError as exc:
        structured_logger.error("Photo not saved to media storage", action="media_store_failed", exception=exc)
    preview = await chat.send_photo(photo=InputFile(processed, filename="photo.jpg"))
    return Photo(id=None, storage_key=key, tg_file_id=preview.photo[-1].file_id)


async def _remember(photo: Photo, message: Message) -> None:
    if photo.id is None or not message.photo:
        return
    file_id = message.photo[-1].file_id
    if file_id != photo.tg_file_id:
        async with get_async_session() as session:
            await catalog.remember_tg_file_id(session, photo.id, file_id)
            await session.commit()


async def send_card(chat: Chat, photo: Photo | None, caption: str, **kwargs) -> Message:
    """Карточка товара: фото с подписью, а если фото нет или его не отправить — просто текст."""
    kwargs.setdefault("parse_mode", "HTML")
    if photo is not None and photo.tg_file_id:
        try:
            return await chat.send_photo(photo=photo.tg_file_id, caption=caption, **kwargs)
        except BadRequest as exc:
            structured_logger.warning(
                "Cached Telegram file_id rejected, sending from storage", action="media_file_id_rejected",
                context={"image_id": photo.id, "error": str(exc)},
            )
    source = _input_file(photo) if photo is not None else None
    if source is None:
        return await chat.send_message(caption, **kwargs)
    message = await chat.send_photo(photo=source, caption=caption, **kwargs)
    await _remember(photo, message)
    return message


async def backfill_media_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Один раз после старта: фото, которые есть только в Telegram, скачать в своё хранилище."""
    stored = failed = 0
    after_id = 0
    while True:
        async with get_async_session() as session:
            batch = await catalog.photos_without_storage(session, BACKFILL_BATCH, after_id)
        if not batch:
            break
        for photo in batch:
            after_id = photo.id
            try:
                data = await download(context.bot, photo.tg_file_id)
                key = await asyncio.to_thread(media.save_product_photo, data)
            except Exception as exc:  # file_id протух, нет места на диске и т.п. — попробуем при следующем старте
                failed += 1
                structured_logger.warning(
                    "Photo not moved to media storage", action="media_backfill_failed",
                    context={"image_id": photo.id, "error": f"{type(exc).__name__}: {exc}"},
                )
                continue
            async with get_async_session() as session:
                await catalog.set_storage_key(session, photo.id, key)
                await session.commit()
            stored += 1
    if stored or failed:
        structured_logger.info(
            "Media backfill finished", action="media_backfill", context={"stored": stored, "failed": failed}
        )
