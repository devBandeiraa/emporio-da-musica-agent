"""Deterministic store rules. The model never does this math on its own."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from emporio_agent.models import Customer, Order, Product, Promotion
from emporio_agent.text import digits_only, round_money

PIX_DISCOUNT_PERCENT = Decimal(5)
MAX_INSTALLMENTS = 12

WITHDRAWAL_DAYS = 7
PREFERENCE_EXCHANGE_DAYS = 7
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90

COUNTRY_CODE = "55"
LOCAL_PHONE_LENGTH = 11


@dataclass(frozen=True)
class Pricing:
    list_price: Decimal
    final_price: Decimal
    promotion: Promotion | None
    pix_price: Decimal | None
    installments: int
    installment_value: Decimal


@dataclass(frozen=True)
class Window:
    deadline: date
    is_open: bool


@dataclass(frozen=True)
class ReturnWindows:
    assumed_received_on: date
    withdrawal: Window
    preference_exchange: Window
    defect_exchange: Window
    legal_warranty: Window


def _discounted(price: Decimal, percent: Decimal) -> Decimal:
    return round_money(price * (100 - percent) / 100)


def minimum_installment(installments: int) -> Decimal:
    """Minimum value of each installment, per the tiers in §3.1."""
    if installments <= 3:
        return Decimal(50)
    if installments <= 6:
        return Decimal(80)
    return Decimal(100)


def max_installments(amount: Decimal) -> int:
    for installments in range(MAX_INSTALLMENTS, 1, -1):
        if amount / installments >= minimum_installment(installments):
            return installments
    return 1


def price_product(product: Product, promotion: Promotion | None) -> Pricing:
    """Apply the active promotion, or else offer PIX: the two never stack (§6.2)."""
    if promotion:
        final_price = _discounted(product.price_brl, Decimal(promotion.discount_percent))
        pix_price = None
    else:
        final_price = round_money(product.price_brl)
        pix_price = _discounted(product.price_brl, PIX_DISCOUNT_PERCENT)

    installments = max_installments(final_price)
    return Pricing(
        list_price=round_money(product.price_brl),
        final_price=final_price,
        promotion=promotion,
        pix_price=pix_price,
        installments=installments,
        installment_value=round_money(final_price / installments),
    )


def return_windows(order: Order, today: date) -> ReturnWindows | None:
    """Policy deadlines of a delivered order; other statuses have not started the clock."""
    if order.status != "delivered" or order.estimated_delivery is None:
        return None

    received_on = order.estimated_delivery

    def window(start: date, days: int) -> Window:
        deadline = start + timedelta(days=days)
        return Window(deadline=deadline, is_open=today <= deadline)

    return ReturnWindows(
        assumed_received_on=received_on,
        withdrawal=window(received_on, WITHDRAWAL_DAYS),
        preference_exchange=window(received_on, PREFERENCE_EXCHANGE_DAYS),
        defect_exchange=window(order.order_date, DEFECT_EXCHANGE_DAYS),
        legal_warranty=window(received_on, LEGAL_WARRANTY_DAYS),
    )


def days_overdue(order: Order, today: date) -> int:
    """How long a shipped order has been past its delivery estimate."""
    if order.status != "shipped" or order.estimated_delivery is None:
        return 0
    return max((today - order.estimated_delivery).days, 0)


def _local_phone(text: str) -> str:
    digits = digits_only(text).lstrip("0")
    if len(digits) > LOCAL_PHONE_LENGTH and digits.startswith(COUNTRY_CODE):
        return digits[len(COUNTRY_CODE) :]
    return digits


def contact_matches(customer: Customer, contact: str) -> bool:
    """Compare a stated e-mail or phone with the one on the customer's record."""
    contact = contact.strip()
    if "@" in contact:
        return contact.casefold() == customer.email.casefold()
    return bool(_local_phone(contact)) and _local_phone(contact) == _local_phone(customer.phone)
