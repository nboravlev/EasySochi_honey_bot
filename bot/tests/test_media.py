"""Хранилище фото и отправка карточек в Telegram (без БД)."""
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage
from telegram.error import BadRequest

from services import media
from services.catalog import Photo
from utils import telegram_media


def image_bytes(width: int, height: int, fmt: str = "PNG") -> bytes:
    out = BytesIO()
    PILImage.new("RGB", (width, height), (10, 200, 10)).save(out, format=fmt)
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    return PILImage.open(BytesIO(data)).size


def test_square_jpeg_crops_and_never_upscales():
    small = media.square_jpeg(image_bytes(300, 200))
    assert size_of(small) == (200, 200) and PILImage.open(BytesIO(small)).format == "JPEG"
    assert size_of(media.square_jpeg(image_bytes(3000, 2000))) == (media.PHOTO_SIZE, media.PHOTO_SIZE)


def test_square_jpeg_rejects_garbage():
    with pytest.raises(media.InvalidImage):
        media.square_jpeg(b"not an image")


def test_storage_round_trip(tmp_path):
    storage = media.MediaStorage(tmp_path)
    key = storage.save(b"data", "products")
    assert key.startswith("products/") and key.endswith(".jpg")
    assert storage.exists(key) and storage.read(key) == b"data"
    assert not list(tmp_path.rglob("*.tmp"))            # временный файл переименован


@pytest.mark.parametrize("key", ["../etc/passwd", "/etc/passwd", "products/../../x", ""])
def test_storage_rejects_unsafe_keys(tmp_path, key):
    with pytest.raises(ValueError):
        media.MediaStorage(tmp_path).path(key)


class FakeChat:
    def __init__(self, reject_file_ids=()):
        self.reject = set(reject_file_ids)
        self.sent = []

    async def send_photo(self, photo, caption=None, **kwargs):
        if isinstance(photo, str) and photo in self.reject:
            raise BadRequest("Wrong file identifier")
        self.sent.append(("photo", photo, caption))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="fresh-id")], message_id=1)

    async def send_message(self, text, **kwargs):
        self.sent.append(("text", None, text))
        return SimpleNamespace(photo=None, message_id=2)


@pytest.fixture
def stored_key(tmp_path, monkeypatch):
    storage = media.MediaStorage(tmp_path)
    monkeypatch.setattr(media, "storage", lambda: storage)
    return storage.save(image_bytes(10, 10, "JPEG"))


async def test_send_card_prefers_cached_file_id(stored_key):
    chat = FakeChat()
    await telegram_media.send_card(chat, Photo(id=None, storage_key=stored_key, tg_file_id="cached"), "Мёд")
    assert chat.sent == [("photo", "cached", "Мёд")]


async def test_send_card_falls_back_to_storage(stored_key):
    chat = FakeChat(reject_file_ids={"stale"})
    await telegram_media.send_card(chat, Photo(id=None, storage_key=stored_key, tg_file_id="stale"), "Мёд")
    [(kind, source, caption)] = chat.sent
    assert kind == "photo" and not isinstance(source, str) and caption == "Мёд"


async def test_send_card_without_photo_sends_text(stored_key):
    chat = FakeChat()
    await telegram_media.send_card(chat, None, "Мёд")
    await telegram_media.send_card(chat, Photo(id=None, storage_key="products/missing.jpg"), "Мёд")
    assert chat.sent == [("text", None, "Мёд"), ("text", None, "Мёд")]
