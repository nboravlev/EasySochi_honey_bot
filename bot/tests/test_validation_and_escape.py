from decimal import Decimal
from types import SimpleNamespace

import pytest

from utils.constants import MAX_PRICE
from utils.escape import safe_html
from utils.validation import parse_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1500", Decimal("1500.00")),
        ("1 500", Decimal("1500.00")),
        ("1500,5", Decimal("1500.50")),
        ("99.999", Decimal("100.00")),
        (str(MAX_PRICE), Decimal(MAX_PRICE).quantize(Decimal("0.01"))),
    ],
)
def test_parse_price_valid(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "0", "-5", "abc", "NaN", "inf", str(MAX_PRICE + 1)])
def test_parse_price_rejects(raw):
    assert parse_price(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [("<b>x</b> & y", "&lt;b&gt;x&lt;/b&gt; &amp; y"), (None, ""), ("", ""), (Decimal("1.5"), "1.5"), (0, "0")],
)
def test_safe_html(raw, expected):
    assert safe_html(raw) == expected


def test_draft_card_escapes_user_input():
    from services.order_texts import draft_card

    order = SimpleNamespace(
        product_count=2,
        customer_comment="<script>&",
        product_size=SimpleNamespace(
            price=Decimal("1500.00"),
            product=SimpleNamespace(name="Мёд <липовый>"),
            sizes=SimpleNamespace(name=Decimal("1.0"), package=SimpleNamespace(name="Банка")),
        ),
    )
    caption = draft_card(order)
    assert "<b>Мёд &lt;липовый&gt;</b>" in caption
    assert "Комментарий: &lt;script&gt;&amp;" in caption
    assert "Количество: 2" in caption
