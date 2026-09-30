"""Жизненный цикл заказа и операции над черновиком без БД."""
from datetime import timedelta
from itertools import pairwise
from decimal import Decimal
from types import SimpleNamespace

import pytest

from domain.enums import OrderStatus as S
from domain.order_flow import ALLOWED_TRANSITIONS, FINAL_STATUSES, InvalidTransition, can_transition
from services.order_texts import manager_card, rub
from services.orders import CommentTooLong, QuantityLimit, change_quantity, decline, set_comment, transition
from utils.constants import MAX_COMMENT_LENGTH, MAX_PRODUCT_COUNT
from utils.timeutils import format_local, to_local, utcnow

HAPPY_PATH = [S.DRAFT, S.CREATED, S.PROCESSING, S.READY, S.CUSTOMER_NOTIFIED, S.RECEIVED]


def make_order(status=S.DRAFT, count=1, price="1500.00"):
    return SimpleNamespace(
        id=7, status_id=status, product_count=count, total_price=Decimal(price) * count,
        customer_comment=None, manager_comment=None, manager_id=None,
        created_at=utcnow() - timedelta(hours=2), updated_at=utcnow() - timedelta(minutes=30),
        product_size=SimpleNamespace(
            price=Decimal(price),
            product=SimpleNamespace(name="Каштановый <мёд>"),
            sizes=SimpleNamespace(name=Decimal("1.0"), package=SimpleNamespace(name="Банка")),
        ),
        user=SimpleNamespace(firstname="Анна", username=None, phone_number=None, identities=[]),
    )


def test_happy_path_is_allowed():
    for current, target in pairwise(HAPPY_PATH):
        assert can_transition(current, target), f"{current.name} → {target.name}"


@pytest.mark.parametrize("final", sorted(FINAL_STATUSES))
def test_final_statuses_have_no_exits(final):
    assert all(not can_transition(final, target) for target in S)


@pytest.mark.parametrize(
    "current, target",
    [
        (S.CREATED, S.RECEIVED),        # нельзя выдать неподтверждённый заказ
        (S.DECLINED, S.RECEIVED),       # и отклонённый
        (S.CREATED, S.CREATED),         # повторный «Заказать»
        (S.CUSTOMER_NOTIFIED, S.DECLINED),
        (S.DRAFT, S.PROCESSING),
        (S.PROCESSING, S.CREATED),
    ],
)
def test_forbidden_transitions(current, target):
    assert not can_transition(current, target)


def test_decline_only_before_handover():
    declinable = {status for status, targets in ALLOWED_TRANSITIONS.items() if S.DECLINED in targets}
    assert declinable == {S.CREATED, S.PROCESSING, S.READY}


def test_transition_updates_status_timestamp_and_manager():
    order = make_order(S.CREATED)
    waited = transition(order, S.PROCESSING, actor_id=111)
    assert order.status_id == S.PROCESSING
    assert order.manager_id == 111
    assert timedelta(minutes=29) < waited < timedelta(minutes=31)
    assert utcnow() - order.updated_at < timedelta(seconds=5)


def test_transition_rejects_and_keeps_order_untouched():
    order = make_order(S.RECEIVED)
    with pytest.raises(InvalidTransition):
        transition(order, S.RECEIVED)
    assert order.status_id == S.RECEIVED


def test_decline_stores_reason_and_default():
    order = make_order(S.CREATED)
    decline(order, "  ", actor_id=111)
    assert order.status_id == S.DECLINED and order.manager_comment == "Причина не указана"
    order = make_order(S.READY)
    decline(order, "x" * 400)
    assert len(order.manager_comment) == 255


def test_change_quantity_recalculates_total_and_limits():
    order = make_order(count=1)
    assert change_quantity(order, +1) and order.product_count == 2
    assert order.total_price == Decimal("3000.00")
    assert not change_quantity(make_order(count=1), -1)      # меньше 1 — без изменений
    order = make_order(count=MAX_PRODUCT_COUNT)
    with pytest.raises(QuantityLimit):
        change_quantity(order, +1)
    assert order.product_count == MAX_PRODUCT_COUNT


def test_set_comment_limit():
    order = make_order()
    set_comment(order, "  позвоните заранее  ")
    assert order.customer_comment == "позвоните заранее"
    with pytest.raises(CommentTooLong):
        set_comment(order, "x" * (MAX_COMMENT_LENGTH + 1))


@pytest.mark.parametrize(
    "amount, text",
    [(Decimal("15000.00"), "15 000 ₽"), (Decimal("1500.5"), "1 500,50 ₽"), (0, "0 ₽"), (None, "0 ₽")],
)
def test_rub(amount, text):
    assert rub(amount) == text


def test_manager_card_escapes_and_uses_local_time():
    order = make_order(S.CREATED)
    card = manager_card(order, "🔔 Новый заказ #7🔔")
    assert "Каштановый &lt;мёд&gt;" in card
    assert "1 500 ₽" in card
    assert format_local(order.created_at) in card
    assert "ВКонтакте" not in card

    # покупатель из VK: продавцу — ссылка на профиль, чтобы связаться
    order.user.identities = [SimpleNamespace(provider="vk", external_id="12345")]
    assert "https://vk.com/id12345" in manager_card(order, "")


def test_local_time_is_moscow_even_for_naive_utc():
    naive_utc = utcnow().replace(tzinfo=None)
    assert to_local(naive_utc).utcoffset() == timedelta(hours=3)
