"""The agent's tools: validated input, JSON output, and no exception ever reaches the loop."""

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from emporio_agent.catalog import empty_category_in, find_category, search_products
from emporio_agent.models import Order, Product
from emporio_agent.policies import (
    Pricing,
    Window,
    contact_matches,
    days_overdue,
    price_product,
    return_windows,
)
from emporio_agent.store import Store
from emporio_agent.text import format_brl

logger = logging.getLogger(__name__)

MAX_FAILED_LOOKUPS = 3
MAX_ALTERNATIVES = 3
DEFAULT_RESULTS = 20

ORDER_NOT_VERIFIED = (
    "Não foi possível confirmar esse pedido com o contato informado. "
    "Peça para o cliente conferir o número do pedido e o e-mail ou telefone da compra. "
    "Não trate o cliente pelo nome: nada foi confirmado."
)
ORDER_LOCKED = (
    "Limite de tentativas atingido nesta conversa. Não tente de novo: "
    "encaminhe o cliente para atendimento humano."
)
RECEIPT_ASSUMPTION = (
    "Avise o cliente: os prazos foram calculados pela previsão de entrega, "
    "porque a data real de recebimento não é registrada."
)
WINDOWS_NOT_STARTED = "O pedido ainda não consta como entregue; os prazos contam do recebimento."

ORDER_STATUS_LABELS = {
    "pending": "pendente",
    "confirmed": "confirmado",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
PAYMENT_LABELS = {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}
AVAILABILITY_GUIDANCE = {
    "out_of_stock": "Temporariamente indisponível: diga isso e ofereça as alternativas.",
    "discontinued": "Não faz mais parte do catálogo: diga isso e ofereça as alternativas.",
    "coming_soon": "Em breve, sem data: não confirme preço nem prometa aviso. Dê alternativas.",
}


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchProductsInput(ToolInput):
    query: str | None = Field(
        default=None,
        description="Marca, modelo ou característica, ex.: 'Takamine GD20' ou 'violão 7 cordas'.",
    )
    category: str | None = Field(default=None, description="Categoria, ex.: 'violões', 'baixos'.")
    max_price: float | None = Field(
        default=None, gt=0, description="Preço final máximo em reais, já com promoção."
    )
    limit: int = Field(default=DEFAULT_RESULTS, ge=1, le=100)

    @model_validator(mode="after")
    def require_a_filter(self) -> "SearchProductsInput":
        if not (self.query or self.category or self.max_price):
            raise ValueError("Informe query, category ou max_price.")
        return self


class ProductDetailsInput(ToolInput):
    product_id: int = Field(description="ID retornado por search_products.")


class GetOrderInput(ToolInput):
    order_id: int = Field(description="Número do pedido informado pelo cliente.")
    contact: str = Field(
        min_length=3,
        description="E-mail ou telefone informado pelo cliente na conversa, nunca presumido.",
    )


class RegisterTicketInput(ToolInput):
    kind: Literal["reclamacao", "cancelamento", "exclusao_de_dados", "atendimento_humano"]
    summary: str = Field(min_length=5, max_length=1000, description="Resumo do caso em português.")
    contact: str | None = Field(default=None, description="Contato informado pelo cliente.")
    order_id: int | None = None


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[Any], dict[str, Any]]


def _format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _payment_label(method: str) -> str:
    if installments := re.fullmatch(r"credit_(\d+)x", method):
        return f"cartão de crédito em {installments.group(1)}x"
    return PAYMENT_LABELS.get(method, method)


def _availability(product: Product) -> str:
    if product.status != "active":
        return product.status
    return "available" if product.is_available else "out_of_stock"


def _payment_summary(pricing: Pricing) -> str:
    """A ready sentence: left to combine fields, the model called the card price a PIX price."""
    final = format_brl(pricing.final_price)
    installments = (
        f"em até {pricing.installments}x sem juros de "
        f"{format_brl(pricing.installment_value)} no cartão"
    )
    if pricing.pix_price is None:
        return f"{final} em qualquer forma de pagamento, inclusive PIX, ou {installments}."
    return (
        f"{format_brl(pricing.pix_price)} no PIX, {final} no débito ou boleto, ou {installments}."
    )


def _pricing_payload(pricing: Pricing) -> dict[str, Any]:
    promotion = pricing.promotion
    return {
        "payment_summary": _payment_summary(pricing),
        "list_price": format_brl(pricing.list_price),
        "promotion": promotion
        and {"name": promotion.description, "discount_percent": promotion.discount_percent},
        "final_price": format_brl(pricing.final_price),
        "pix_price": pricing.pix_price and format_brl(pricing.pix_price),
        "pix_note": "PIX não acumula com promoção." if promotion else None,
        "max_installments_without_interest": pricing.installments,
        "installment_value": format_brl(pricing.installment_value),
    }


def _window_payload(window: Window) -> dict[str, Any]:
    return {"deadline": _format_date(window.deadline), "open": window.is_open}


class Toolbox:
    """Tools for one conversation. Failed order lookups are counted per instance."""

    def __init__(self, store: Store, now: Callable[[], datetime], tickets_path: Path) -> None:
        self._store = store
        self._now = now
        self._tickets_path = tickets_path
        self._failed_lookups = 0
        tools = [
            Tool(
                name="search_products",
                description=(
                    "Busca produtos no catálogo por texto, categoria e preço final máximo. "
                    "`results` traz só o que pode ser comprado agora. `not_available` traz o que "
                    "combina com a busca mas não pode ser comprado: use para responder sobre "
                    "aquele produto, nunca como opção. `similar` traz parecidos quando não há "
                    "resultado exato."
                ),
                input_model=SearchProductsInput,
                handler=self._search_products,
            ),
            Tool(
                name="get_product_details",
                description=(
                    "Detalhes de um produto: disponibilidade, specs, preço com promoção, PIX, "
                    "parcelamento e alternativas. Use antes de afirmar preço, estoque ou promoção."
                ),
                input_model=ProductDetailsInput,
                handler=self._get_product_details,
            ),
            Tool(
                name="get_order",
                description=(
                    "Consulta um pedido, sempre com o número e o e-mail ou telefone informados "
                    "pelo cliente. Traz status, itens, total registrado, rastreio e os prazos "
                    "de troca e devolução já calculados."
                ),
                input_model=GetOrderInput,
                handler=self._get_order,
            ),
            Tool(
                name="register_ticket",
                description=(
                    "Registra um caso para a equipe: reclamação, cancelamento, exclusão de dados "
                    "ou pedido de atendimento humano. Só diga que registrou depois de chamar."
                ),
                input_model=RegisterTicketInput,
                handler=self._register_ticket,
            ),
        ]
        self._tools = {tool.name: tool for tool in tools}

    def definitions(self) -> list[dict[str, Any]]:
        """Tool schemas in the format the Messages API expects."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return self._error({"error": "unknown_tool", "name": name})
        try:
            payload = tool.handler(tool.input_model.model_validate(arguments))
        except ValidationError as error:
            details = [issue["msg"] for issue in error.errors()]
            return self._error({"error": "invalid_input", "details": details})
        except Exception:
            # A failing tool must become a message the model can recover from, not a crash.
            logger.exception("Tool %s failed", name)
            return self._error({"error": "internal_error", "retry": False})
        return ToolResult(json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _error(payload: dict[str, Any]) -> ToolResult:
        return ToolResult(json.dumps(payload, ensure_ascii=False), is_error=True)

    def _pricing(self, product: Product) -> Pricing:
        return price_product(product, self._store.active_promotion(product.product_id))

    def _summary(self, product: Product) -> dict[str, Any]:
        pricing = self._pricing(product)
        category = self._store.categories[product.category_id]
        return {
            "product_id": product.product_id,
            "name": product.name,
            "category": category.name,
            "final_price": format_brl(pricing.final_price),
            "list_price": format_brl(pricing.list_price),
            "discount_percent": pricing.promotion and pricing.promotion.discount_percent,
            "stock": product.stock_quantity,
        }

    def _not_available_summary(self, product: Product) -> dict[str, Any]:
        availability = _availability(product)
        return {
            "product_id": product.product_id,
            "name": product.name,
            "availability": availability,
            "guidance": AVAILABILITY_GUIDANCE[availability],
            "alternatives": self._alternatives(product),
        }

    def _stocked_categories(self) -> list[str]:
        stocked = {product.category_id for product in self._store.products.values()}
        return [self._store.categories[category_id].name for category_id in sorted(stocked)]

    def _search_products(self, args: SearchProductsInput) -> dict[str, Any]:
        category = None
        if args.category:
            category = find_category(self._store, args.category)
            if category is None:
                return {
                    "total": 0,
                    "results": [],
                    "unknown_category": args.category,
                    "categories_with_products": self._stocked_categories(),
                }

        empty = empty_category_in(self._store, " ".join(filter(None, [args.query, args.category])))
        if empty:
            return {
                "total": 0,
                "results": [],
                "category_without_products": empty.name,
                "categories_with_products": self._stocked_categories(),
            }

        similar: list[Product] = []
        if args.query:
            found = search_products(self._store, args.query)
            candidates, similar = found.matches, found.similar
        else:
            candidates = list(self._store.products.values())

        if category:
            candidates = [p for p in candidates if p.category_id == category.category_id]
        if args.max_price:
            limit = Decimal(str(args.max_price))
            candidates = [p for p in candidates if self._pricing(p).final_price <= limit]

        available = [p for p in candidates if p.is_available]
        is_listing = bool(args.category or args.max_price or not args.query)
        if is_listing:
            available.sort(key=lambda p: self._pricing(p).final_price)

        payload: dict[str, Any] = {
            "total": len(available),
            "results": [self._summary(p) for p in available[: args.limit]],
        }
        if len(available) > args.limit:
            payload["showing"] = args.limit
        # Shopping lists leave these out: only a direct question needs them.
        if not is_listing and (not_available := [p for p in candidates if not p.is_available]):
            payload["not_available"] = [self._not_available_summary(p) for p in not_available]
        if not candidates and (options := [p for p in similar if p.is_available]):
            payload["similar"] = [self._summary(p) for p in options]
        return payload

    def _alternatives(self, product: Product) -> list[dict[str, Any]]:
        options = [
            p
            for p in self._store.products.values()
            if p.is_available and p.category_id == product.category_id
        ]
        options.sort(key=lambda p: abs(self._pricing(p).final_price - product.price_brl))
        return [self._summary(p) for p in options[:MAX_ALTERNATIVES]]

    def _get_product_details(self, args: ProductDetailsInput) -> dict[str, Any]:
        product = self._store.products.get(args.product_id)
        if product is None:
            return {"found": False, "message": "Produto não encontrado no catálogo."}

        availability = _availability(product)
        expired = {p.description for p in self._store.expired_promotions(product.product_id)}
        payload: dict[str, Any] = {
            "found": True,
            "product_id": product.product_id,
            "name": product.name,
            "category": self._store.categories[product.category_id].name,
            "availability": availability,
            "specs": product.specs,
            "description": product.description,
            "expired_promotions": sorted(expired),
        }
        if availability == "available":
            payload["stock"] = product.stock_quantity
        else:
            payload["guidance"] = AVAILABILITY_GUIDANCE[availability]
            payload["alternatives"] = self._alternatives(product)
        if product.status == "active":
            payload["pricing"] = _pricing_payload(self._pricing(product))
        return payload

    def _order_payload(self, order: Order) -> dict[str, Any]:
        today = self._now().date()
        first_name = self._store.customer_of(order).name.split()[0]
        payload: dict[str, Any] = {
            "verified": True,
            "order_id": order.order_id,
            "customer_first_name": first_name,
            "status": ORDER_STATUS_LABELS[order.status],
            "order_date": _format_date(order.order_date),
            "items": [
                {"name": self._store.products[i.product_id].name, "quantity": i.quantity}
                for i in order.items
            ],
            "recorded_total": format_brl(order.total_brl),
            "payment": _payment_label(order.payment_method),
            "tracking_code": order.tracking_code,
            "estimated_delivery": order.estimated_delivery
            and _format_date(order.estimated_delivery),
            "notes": order.notes,
        }
        if order.status == "shipped":
            payload["days_past_estimate"] = days_overdue(order, today)
            payload["return_windows"] = {"started": False, "reason": WINDOWS_NOT_STARTED}
        elif windows := return_windows(order, today):
            payload["return_windows"] = {
                "started": True,
                "assumed_received_on": _format_date(windows.assumed_received_on),
                "assumption": RECEIPT_ASSUMPTION,
                "withdrawal_7_days": _window_payload(windows.withdrawal),
                "preference_exchange_7_days": _window_payload(windows.preference_exchange),
                "defect_exchange_30_days": _window_payload(windows.defect_exchange),
                "legal_warranty_90_days": _window_payload(windows.legal_warranty),
            }
        return payload

    def _get_order(self, args: GetOrderInput) -> dict[str, Any]:
        if self._failed_lookups >= MAX_FAILED_LOOKUPS:
            return {"verified": False, "locked": True, "message": ORDER_LOCKED}

        order = self._store.orders.get(args.order_id)
        if order is None or not contact_matches(self._store.customer_of(order), args.contact):
            # Same answer for both cases, so order numbers cannot be probed.
            self._failed_lookups += 1
            return {"verified": False, "message": ORDER_NOT_VERIFIED}
        return self._order_payload(order)

    def _register_ticket(self, args: RegisterTicketInput) -> dict[str, Any]:
        ticket_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        ticket = {
            "ticket_id": ticket_id,
            "created_at": self._now().isoformat(),
            **args.model_dump(),
        }

        self._tickets_path.parent.mkdir(parents=True, exist_ok=True)
        with self._tickets_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(ticket, ensure_ascii=False) + "\n")

        payload: dict[str, Any] = {"registered": True, "ticket_id": ticket_id}
        if args.kind == "reclamacao":
            payload["response_time"] = "24 horas úteis"
        return payload
