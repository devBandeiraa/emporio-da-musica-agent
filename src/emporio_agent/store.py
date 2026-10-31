"""Loads the CSV files into validated, in-memory records."""

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from emporio_agent.models import Category, Customer, Order, OrderItem, Product, Promotion

# Descriptions in this block contradict the product's name or specs: "Music Man Bass 1X"
# is described as a Fender Jazz Bass, "Yamaha Bass 3X" as a 5-string Ibanez. Dropping them
# at load time keeps them out of both the answers and the search index.
UNRELIABLE_DESCRIPTION_IDS = frozenset(range(135, 145))


class DataError(Exception):
    """The store's files are missing or inconsistent."""


@dataclass(frozen=True)
class Store:
    categories: dict[int, Category]
    products: dict[int, Product]
    customers: dict[int, Customer]
    orders: dict[int, Order]
    promotions: tuple[Promotion, ...]

    def active_promotion(self, product_id: int) -> Promotion | None:
        active = [p for p in self.promotions if p.product_id == product_id and p.is_active]
        return max(active, key=lambda p: p.discount_percent, default=None)

    def expired_promotions(self, product_id: int) -> list[Promotion]:
        return [p for p in self.promotions if p.product_id == product_id and not p.is_active]

    def customer_of(self, order: Order) -> Customer:
        return self.customers[order.customer_id]


def _read_csv(path: Path) -> Iterator[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            yield from csv.DictReader(file)
    except FileNotFoundError as error:
        raise DataError(f"Missing data file: {path}") from error


def _load_product(row: dict[str, str]) -> Product:
    if int(row["product_id"]) in UNRELIABLE_DESCRIPTION_IDS:
        row = {**row, "description": None}
    return Product.model_validate(row)


def _check_references(store: Store) -> None:
    for product in store.products.values():
        if product.category_id not in store.categories:
            raise DataError(f"Product {product.product_id} has an unknown category")
    for promotion in store.promotions:
        if promotion.product_id not in store.products:
            raise DataError(f"Promotion {promotion.promotion_id} has an unknown product")
    for order in store.orders.values():
        if order.customer_id not in store.customers:
            raise DataError(f"Order {order.order_id} has an unknown customer")
        if not order.items:
            raise DataError(f"Order {order.order_id} has no items")
        for item in order.items:
            if item.product_id not in store.products:
                raise DataError(f"Order {order.order_id} has an unknown product")


def load_store(data_dir: Path) -> Store:
    items: dict[int, list[OrderItem]] = {}
    for row in _read_csv(data_dir / "order_items.csv"):
        items.setdefault(int(row["order_id"]), []).append(OrderItem.model_validate(row))

    categories = [Category.model_validate(r) for r in _read_csv(data_dir / "categories.csv")]
    products = [_load_product(r) for r in _read_csv(data_dir / "products.csv")]
    customers = [Customer.model_validate(r) for r in _read_csv(data_dir / "customers.csv")]
    orders = [
        Order.model_validate({**row, "items": items.get(int(row["order_id"]), ())})
        for row in _read_csv(data_dir / "orders.csv")
    ]
    promotions = [Promotion.model_validate(r) for r in _read_csv(data_dir / "promotions.csv")]

    store = Store(
        categories={c.category_id: c for c in categories},
        products={p.product_id: p for p in products},
        customers={c.customer_id: c for c in customers},
        orders={o.order_id: o for o in orders},
        promotions=tuple(promotions),
    )
    _check_references(store)
    return store
