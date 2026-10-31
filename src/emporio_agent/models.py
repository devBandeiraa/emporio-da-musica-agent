"""Typed records for the store's CSV files. Field names follow the CSV columns."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Json, NonNegativeInt, PositiveInt

ProductStatus = Literal["active", "discontinued", "coming_soon"]
OrderStatus = Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]


def _blank_to_none(value: object) -> object:
    return None if value == "" else value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
OptionalDate = Annotated[date | None, BeforeValidator(_blank_to_none)]


class Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Category(Record):
    category_id: int
    name: str
    description: str


class Product(Record):
    product_id: int
    name: str
    category_id: int
    price_brl: Annotated[Decimal, BeforeValidator(str)]
    stock_quantity: NonNegativeInt
    status: ProductStatus
    specs: Json[dict[str, str]]
    # None means the catalog text cannot be trusted (see UNRELIABLE_DESCRIPTION_IDS).
    description: str | None
    created_at: date

    @property
    def is_available(self) -> bool:
        """Status wins over stock: discontinued item 136 still shows 13 units."""
        return self.status == "active" and self.stock_quantity > 0


class Customer(Record):
    customer_id: int
    name: str
    phone: str
    email: str
    city: str


class OrderItem(Record):
    product_id: int
    quantity: PositiveInt


class Order(Record):
    order_id: int
    customer_id: int
    order_date: date
    status: OrderStatus
    total_brl: Annotated[Decimal, BeforeValidator(str)]
    payment_method: str
    tracking_code: OptionalText
    estimated_delivery: OptionalDate
    notes: OptionalText
    items: tuple[OrderItem, ...]


class Promotion(Record):
    promotion_id: int
    product_id: int
    discount_percent: PositiveInt
    description: str
    is_active: bool
