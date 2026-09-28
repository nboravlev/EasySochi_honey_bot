from enum import IntEnum, StrEnum


class OrderStatus(IntEnum):
    """ID строк справочника order_statuses (сидятся миграцией b1c2d3e4f5a6)."""
    CREATED = 1             # покупатель нажал «Заказать»
    CUSTOMER_NOTIFIED = 2   # покупатель сообщил, когда заберёт заказ
    PROCESSING = 3          # продавец подтвердил заказ
    READY = 4               # заказ готов к выдаче
    RECEIVED = 5            # заказ выдан и оплачен
    DECLINED = 6            # отклонён продавцом
    EXPIRED = 7             # черновик не оформлен вовремя
    DRAFT = 8               # черновик, покупатель ещё собирает заказ


class Role(IntEnum):
    """ID строк справочника roles.

    В users.role_id используются USER и MANAGER; BUYER — роль сессии покупки (журнал).
    TASTING оставлена для старых сессий записи на дегустацию (теперь — tasting_signups).
    """
    USER = 1
    BUYER = 2
    TASTING = 3
    MANAGER = 4


class TastingStatus(StrEnum):
    WAITING = "waiting"     # записался, ждёт приглашения
    INVITED = "invited"     # получил приглашение на конкретное мероприятие
    GOING = "going"         # ответил «Приду»
    DECLINED = "declined"   # ответил «Не смогу»


class NotificationStatus(StrEnum):
    PENDING = "pending"     # ждёт отправки (в том числе повторной)
    SENT = "sent"
    FAILED = "failed"       # отправить нельзя (бот заблокирован, чата нет) или попытки исчерпаны


class Provider(StrEnum):
    """Платформа, через которую человек пользуется системой (user_identities, shop_channels)."""
    TELEGRAM = "telegram"
    VK = "vk"
    MAX = "max"
    WEB = "web"
