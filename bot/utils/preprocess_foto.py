from io import BytesIO
from PIL import Image as PILImage
from telegram import InputFile, Update

TARGET_SIZE = 512  # размер стороны квадрата в пикселях

async def preprocess_photo_crop_center(file_id: str, bot, chat_id: int) -> str:
    """
    Скачивает фото из Telegram, делает квадратный кроп по центру,
    масштабирует до TARGET_SIZE x TARGET_SIZE и возвращает новый file_id.
    """
    # Скачиваем исходный файл
    tg_file = await bot.get_file(file_id)
    file_bytes = BytesIO()
    await tg_file.download_to_memory(out=file_bytes)
    file_bytes.seek(0)

    # Открываем изображение
    img = PILImage.open(file_bytes).convert("RGB")
    width, height = img.size
    min_dim = min(width, height)

    # Кроп по центру
    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    right = left + min_dim
    bottom = top + min_dim
    img_cropped = img.crop((left, top, right, bottom))

    # Масштабируем до TARGET_SIZE x TARGET_SIZE
    img_cropped = img_cropped.resize((TARGET_SIZE, TARGET_SIZE), PILImage.LANCZOS)

    # Сохраняем в буфер
    output = BytesIO()
    img_cropped.save(output, format="JPEG", quality=90)
    output.seek(0)

    # Отправляем обратно в Telegram (например, в тестовый чат)
    sent = await bot.send_photo(chat_id=chat_id, photo=InputFile(output))
    
    return sent.photo[-1].file_id
