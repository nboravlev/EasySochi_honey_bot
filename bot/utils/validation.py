from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from utils.constants import MAX_PRICE


def parse_price(text: str | None) -> Decimal | None:
    """Разбирает цену из ввода менеджера: «1500», «1 500», «1500,50».

    Возвращает Decimal с двумя знаками или None, если ввод не цена
    (не число, <= 0 или больше MAX_PRICE).
    """
    if not text:
        return None
    normalized = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        price = Decimal(normalized)
    except InvalidOperation:
        return None
    if not price.is_finite() or price <= 0 or price > MAX_PRICE:
        return None
    return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
