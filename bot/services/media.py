"""Собственное хранилище фото: файлы на томе (MEDIA_DIR), в БД — только ключ «products/<uuid>.jpg».

Фото не зависят от платформы: Telegram file_id — лишь кэш для быстрой повторной отправки,
сайт и VK будут брать тот же файл. Хранилище файловое; при переезде в S3 меняется только этот модуль.
"""
import os
import uuid
from functools import lru_cache
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

from config import get_settings

PRODUCTS = "products"
PHOTO_SIZE = 1024          # сторона квадрата; меньшие фото не растягиваем
JPEG_QUALITY = 88


class InvalidImage(ValueError):
    """Файл не читается как изображение."""


def square_jpeg(data: bytes, size: int = PHOTO_SIZE) -> bytes:
    """Квадрат по центру, не больше size×size, JPEG. Учитывает поворот из EXIF (фото с телефона)."""
    try:
        img = PILImage.open(BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage(str(exc)) from exc
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    if side > size:
        img = img.resize((size, size), PILImage.LANCZOS)
    out = BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


class MediaStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or PurePosixPath(key).is_absolute() or ".." in parts:
            raise ValueError(f"недопустимый ключ файла: {key!r}")
        return self.root.joinpath(*parts)

    def save(self, data: bytes, folder: str = PRODUCTS, suffix: str = ".jpg") -> str:
        """Записать файл (атомарно: сначала во временный) и вернуть его ключ."""
        key = f"{folder}/{uuid.uuid4().hex}{suffix}"
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return key

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()


@lru_cache
def storage() -> MediaStorage:
    return MediaStorage(get_settings().media_dir)


def save_product_photo(data: bytes) -> str:
    """Обработать фото товара и сохранить; вернуть ключ. Синхронно — вызывать через asyncio.to_thread."""
    return storage().save(square_jpeg(data), PRODUCTS)
