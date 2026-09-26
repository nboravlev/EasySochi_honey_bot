from datetime import timedelta, timezone
from enum import IntEnum

# Пасека работает по Москве, сервер — в другом поясе (Екатеринбург), контейнер — в UTC
BUSINESS_TZ = timezone(timedelta(hours=3), name="MSK")


class OrderStatus(IntEnum):
    """ID строк справочника order_statuses (сидятся миграцией b1c2d3e4f5a6)."""
    CREATED = 1             # покупатель нажал «Заказать»
    CUSTOMER_NOTIFIED = 2   # покупатель сообщил, когда заберёт заказ
    PROCESSING = 3          # продавец подтвердил заказ
    READY = 4               # заказ готов к выдаче
    RECEIVED = 5            # заказ выдан и оплачен
    DECLINED = 6            # отклонён продавцом
    EXPIRED = 7             # время истекло
    DRAFT = 8               # черновик, покупатель ещё собирает заказ


class Role(IntEnum):
    """ID строк справочника roles."""
    USER = 1
    BUYER = 2
    TASTING = 3
    MANAGER = 4


APIARY_ADDRESS = "Красная Поляна, ул. Плотинная, д. 4"

MAX_PRODUCT_COUNT = 20        # банок одного товара в заказе
MAX_PRICE = 1_000_000         # ₽ за одну позицию
MAX_COMMENT_LENGTH = 255      # orders.customer_comment VARCHAR(255)
MAX_PRODUCT_NAME_LENGTH = 100
