"""Исходящее сообщение в нейтральном формате: его умеет показать любой фронтенд (Telegram, VK, …).

Текст — безопасное подмножество HTML: <b> <i> <u> <s> <code> <pre> <a href="…">, пользовательские
данные экранируются (utils.escape.safe_html). Кнопки — строки кнопок; у кнопки либо action (данные,
которые вернутся боту при нажатии: «confirm_order_15»), либо url (ссылка).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Button:
    text: str
    action: str | None = None
    url: str | None = None

    def __post_init__(self):
        if (self.action is None) == (self.url is None):
            raise ValueError("у кнопки должно быть ровно одно из: action, url")


@dataclass(frozen=True)
class OutMessage:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)

    def to_payload(self) -> dict:
        payload: dict = {"text": self.text}
        if self.buttons:
            payload["buttons"] = [
                [{k: v for k, v in (("text", b.text), ("action", b.action), ("url", b.url)) if v is not None}
                 for b in row]
                for row in self.buttons
            ]
        return payload

    @classmethod
    def from_payload(cls, payload: dict) -> "OutMessage":
        return cls(
            text=payload["text"],
            buttons=[[Button(**b) for b in row] for row in payload.get("buttons", [])],
        )


@dataclass(frozen=True)
class ToUser:
    """Получатель — человек (users.id): сообщение уйдёт во все его платформы с push-доставкой."""
    user_id: int


@dataclass(frozen=True)
class ToShopStaff:
    """Получатель — персонал магазина: служебные каналы магазина (shop_channels, purpose='staff')."""
    shop_id: int


Recipient = ToUser | ToShopStaff
