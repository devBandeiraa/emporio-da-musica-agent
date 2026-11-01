import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_agent.store import UNRELIABLE_DESCRIPTION_IDS, DataError, load_store

DATA_DIR = Path(__file__).parent.parent / "data"


def test_loads_every_table(store):
    assert len(store.categories) == 9
    assert len(store.products) == 65
    assert len(store.customers) == 50
    assert len(store.orders) == 20
    assert len(store.promotions) == 25


def test_parses_types(store):
    product = store.products[95]
    assert product.price_brl == Decimal("2199")
    assert product.stock_quantity == 5
    assert product.created_at == date(2021, 11, 3)
    assert product.specs["top"] == "Cedro Sólido"


def test_blank_order_fields_become_none(store):
    order = store.orders[9]
    assert order.tracking_code is None
    assert order.estimated_delivery is None
    assert order.notes is None


def test_groups_items_by_order(store):
    assert [item.product_id for item in store.orders[15].items] == [82, 106]
    assert store.orders[3].items[0].quantity == 2


def test_unreliable_descriptions_are_dropped(store):
    for product_id in UNRELIABLE_DESCRIPTION_IDS:
        assert store.products[product_id].description is None
    assert store.products[95].description is not None
    assert store.products[134].description is not None
    assert store.products[145].description is not None


@pytest.mark.parametrize(
    ("product_id", "available"),
    [
        (95, True),  # active with stock
        (96, False),  # active, out of stock
        (113, False),  # discontinued, no stock
        (136, False),  # discontinued, 13 in stock
        (130, False),  # coming soon, 2 in stock
    ],
)
def test_availability_depends_on_status_and_stock(store, product_id, available):
    assert store.products[product_id].is_available is available


def test_only_four_promotions_are_active(store):
    active = {p.product_id: p.discount_percent for p in store.promotions if p.is_active}
    assert active == {90: 18, 94: 8, 121: 20, 127: 10}


def test_active_promotion_lookup(store):
    assert store.active_promotion(94).discount_percent == 8
    assert store.active_promotion(95) is None


def test_expired_promotions_keep_every_inactive_row(store):
    assert len(store.expired_promotions(96)) == 2
    assert store.expired_promotions(94) == []


def test_customer_of_returns_the_order_owner(store):
    assert store.customer_of(store.orders[8]).email == "anacarol.ferreira@coldmail.com"


def test_missing_file_raises_data_error(tmp_path):
    with pytest.raises(DataError, match="Missing data file"):
        load_store(tmp_path)


@pytest.mark.parametrize(
    ("file_name", "old", "new", "message"),
    [
        ("orders.csv", ",3,2025-10-15,", ",999,2025-10-15,", "unknown customer"),
        ("products.csv", "Yamaha C40 Nylon Natural,5,", "Yamaha C40 Nylon Natural,99,", "category"),
        ("promotions.csv", "1,102,10,", "1,9999,10,", "Promotion 1 has an unknown product"),
        ("order_items.csv", "1,1,93", "1,1,9999", "Order 1 has an unknown product"),
        ("order_items.csv", "1,1,93", "99,1,93", "Order 1 has no items"),
    ],
)
def test_broken_reference_raises_data_error(tmp_path, file_name, old, new, message):
    for file in DATA_DIR.glob("*.csv"):
        shutil.copy(file, tmp_path / file.name)
    broken = tmp_path / file_name
    broken.write_text(broken.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(DataError, match=message):
        load_store(tmp_path)
