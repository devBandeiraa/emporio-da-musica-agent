from datetime import date
from decimal import Decimal

import pytest

from emporio_agent.policies import (
    contact_matches,
    days_overdue,
    max_installments,
    price_product,
    return_windows,
)

REFERENCE_DATE = date(2026, 3, 25)


def pricing_for(store, product_id):
    return price_product(store.products[product_id], store.active_promotion(product_id))


def test_promotion_price_excludes_pix(store):
    pricing = pricing_for(store, 94)
    assert pricing.list_price == Decimal("5999.00")
    assert pricing.final_price == Decimal("5519.08")
    assert pricing.pix_price is None


def test_pix_discount_applies_without_promotion(store):
    pricing = pricing_for(store, 95)
    assert pricing.final_price == Decimal("2199.00")
    assert pricing.pix_price == Decimal("2089.05")


def test_expired_promotion_does_not_change_the_price(store):
    assert pricing_for(store, 91).final_price == Decimal("899.00")


def test_installments_use_the_final_price(store):
    pricing = pricing_for(store, 121)
    assert pricing.final_price == Decimal("439.20")
    assert pricing.installments == 5
    assert pricing.installment_value == Decimal("87.84")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("40", 1),  # 2x would be below R$ 50
        ("159.90", 3),  # 3x of 53.30
        ("349.90", 4),  # 4x of 87.47; 5x would be below R$ 80
        ("480", 6),  # exactly R$ 80
        ("479.99", 5),
        ("1199", 11),  # 12x would be below R$ 100
        ("1200", 12),  # exactly R$ 100
        ("50000", 12),
    ],
)
def test_max_installments_follow_the_tiers(amount, expected):
    assert max_installments(Decimal(amount)) == expected


def test_window_boundaries_on_a_delivered_order(store):
    order = store.orders[7]  # ordered 2026-02-03, estimated 2026-02-17
    inside = return_windows(order, date(2026, 2, 24))
    outside = return_windows(order, date(2026, 2, 25))

    assert inside.assumed_received_on == date(2026, 2, 17)
    assert inside.withdrawal.deadline == date(2026, 2, 24)
    assert inside.withdrawal.is_open is True
    assert inside.preference_exchange.is_open is True
    assert outside.withdrawal.is_open is False


def test_defect_window_counts_from_the_purchase(store):
    windows = return_windows(store.orders[7], REFERENCE_DATE)
    assert windows.defect_exchange.deadline == date(2026, 3, 5)
    assert windows.defect_exchange.is_open is False


def test_legal_warranty_counts_from_receipt(store):
    assert return_windows(store.orders[7], REFERENCE_DATE).legal_warranty.deadline == date(
        2026, 5, 18
    )


def test_reference_date_leaves_only_legal_warranty_open(store):
    delivered = [order for order in store.orders.values() if order.status == "delivered"]
    windows = {order.order_id: return_windows(order, REFERENCE_DATE) for order in delivered}

    assert not any(w.withdrawal.is_open for w in windows.values())
    assert not any(w.defect_exchange.is_open for w in windows.values())
    assert {oid for oid, w in windows.items() if w.legal_warranty.is_open} == {5, 6, 7}


@pytest.mark.parametrize("order_id", [8, 9, 13, 17])
def test_orders_not_delivered_have_no_windows(store, order_id):
    assert return_windows(store.orders[order_id], REFERENCE_DATE) is None


def test_days_overdue_only_applies_to_shipped_orders(store):
    assert days_overdue(store.orders[8], REFERENCE_DATE) == 25
    assert days_overdue(store.orders[8], date(2026, 2, 20)) == 0
    assert days_overdue(store.orders[7], REFERENCE_DATE) == 0


@pytest.mark.parametrize(
    "contact",
    [
        "anacarol.ferreira@coldmail.com",
        "  ANACAROL.FERREIRA@coldmail.com ",
        "(67) 99654-7821",
        "67996547821",
        "+55 67 99654-7821",
        "067 99654 7821",
    ],
)
def test_contact_matches_accepts_equivalent_forms(store, contact):
    assert contact_matches(store.customers[2], contact) is True


@pytest.mark.parametrize(
    "contact",
    ["outra@coldmail.com", "99654-7821", "(67) 98432-1098", "sem contato", "---"],
)
def test_contact_matches_rejects_everything_else(store, contact):
    assert contact_matches(store.customers[2], contact) is False
