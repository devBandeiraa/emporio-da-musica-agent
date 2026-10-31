import json
from datetime import datetime

import pytest

from emporio_agent.tools import MAX_FAILED_LOOKUPS, Toolbox

NOW = datetime(2026, 3, 25, 10, 0)
ANA_EMAIL = "anacarol.ferreira@coldmail.com"


@pytest.fixture
def toolbox(store, tmp_path):
    return Toolbox(store, now=lambda: NOW, tickets_path=tmp_path / "tickets.jsonl")


def call(toolbox, name, **arguments):
    result = toolbox.execute(name, arguments)
    assert result.is_error is False, result.content
    return json.loads(result.content)


def result_ids(payload):
    return [item["product_id"] for item in payload["results"]]


class TestSearchProducts:
    def test_finds_a_product_by_name(self, toolbox):
        payload = call(toolbox, "search_products", query="Takamine GD20")
        assert payload["results"][0]["name"] == "Takamine GD20 Dreadnought Natural"
        assert payload["results"][0]["final_price"] == "R$ 2.199,00"
        assert payload["results"][0]["stock"] == 5

    def test_price_list_hides_what_cannot_be_bought(self, toolbox):
        payload = call(toolbox, "search_products", category="violões", max_price=1000)
        ids = result_ids(payload)
        assert payload["total"] == 12
        assert 96 not in ids  # Giannini GF-3D, out of stock
        assert 113 not in ids  # Shelby SN-7C, discontinued
        assert "not_available" not in payload

    def test_price_list_is_sorted_from_cheapest(self, toolbox):
        payload = call(toolbox, "search_products", category="violões", max_price=1000)
        assert result_ids(payload)[0] == 83

    def test_price_filter_uses_the_promotional_price(self, toolbox):
        payload = call(toolbox, "search_products", category="ukulele", max_price=450)
        promotional = next(i for i in payload["results"] if i["product_id"] == 121)
        assert promotional["final_price"] == "R$ 439,20"
        assert promotional["list_price"] == "R$ 549,00"
        assert promotional["discount_percent"] == 20

    @pytest.mark.parametrize(
        ("query", "product_id", "availability"),
        [
            ("Giannini GF-3D", 96, "out_of_stock"),
            ("Shelby SN-7C", 113, "discontinued"),
            ("Ibanez Bass 2X", 136, "discontinued"),
            ("Kala KA-ABP-CTG", 130, "coming_soon"),
        ],
    )
    def test_direct_question_explains_unavailable_products(
        self, toolbox, query, product_id, availability
    ):
        payload = call(toolbox, "search_products", query=query)
        assert payload["results"] == []
        assert payload["not_available"][0]["product_id"] == product_id
        assert payload["not_available"][0]["availability"] == availability
        assert payload["not_available"][0]["alternatives"]

    @pytest.mark.parametrize("query", ["saxofone", "saxofone alto", "flauta", "violino"])
    def test_query_for_empty_category_says_so(self, toolbox, query):
        payload = call(toolbox, "search_products", query=query)
        assert payload["results"] == []
        assert payload["category_without_products"]
        assert "Violões" in payload["categories_with_products"]

    def test_empty_category_filter_says_so(self, toolbox):
        payload = call(toolbox, "search_products", category="Cordas Orquestrais")
        assert payload["category_without_products"] == "Cordas Orquestrais"

    def test_unknown_category(self, toolbox):
        payload = call(toolbox, "search_products", category="gaitas")
        assert payload["unknown_category"] == "gaitas"
        assert "Guitarras" in payload["categories_with_products"]

    def test_unknown_model_offers_similar_available_products(self, toolbox):
        payload = call(toolbox, "search_products", query="Takamine GD99")
        assert payload["results"] == []
        assert all("Takamine" in item["name"] for item in payload["similar"])

    def test_contradicted_description_finds_nothing(self, toolbox):
        assert call(toolbox, "search_products", query="Fender Jazz Bass")["results"] == []

    def test_limit_reports_the_full_total(self, toolbox):
        payload = call(toolbox, "search_products", category="violões", limit=5)
        assert payload["total"] == 33
        assert payload["showing"] == 5
        assert len(payload["results"]) == 5

    def test_requires_at_least_one_filter(self, toolbox):
        result = toolbox.execute("search_products", {})
        assert result.is_error is True
        assert "invalid_input" in result.content


class TestProductDetails:
    def test_active_promotion_shows_original_percent_and_final(self, toolbox):
        payload = call(toolbox, "get_product_details", product_id=94)
        pricing = payload["pricing"]
        assert pricing["list_price"] == "R$ 5.999,00"
        assert pricing["promotion"] == {"name": "Desconto Exclusivo", "discount_percent": 8}
        assert pricing["final_price"] == "R$ 5.519,08"
        assert pricing["pix_price"] is None
        assert "não acumula" in pricing["pix_note"]

    def test_payment_summary_separates_pix_from_other_methods(self, toolbox):
        pricing = call(toolbox, "get_product_details", product_id=91)["pricing"]
        assert pricing["payment_summary"] == (
            "R$ 854,05 no PIX, R$ 899,00 no débito ou boleto, "
            "ou em até 8x sem juros de R$ 112,38 no cartão."
        )

    def test_payment_summary_with_a_promotion_has_a_single_price(self, toolbox):
        pricing = call(toolbox, "get_product_details", product_id=94)["pricing"]
        assert pricing["payment_summary"] == (
            "R$ 5.519,08 em qualquer forma de pagamento, inclusive PIX, "
            "ou em até 12x sem juros de R$ 459,92 no cartão."
        )

    def test_no_promotion_offers_pix(self, toolbox):
        pricing = call(toolbox, "get_product_details", product_id=95)["pricing"]
        assert pricing["promotion"] is None
        assert pricing["pix_price"] == "R$ 2.089,05"
        assert pricing["max_installments_without_interest"] == 12
        assert pricing["installment_value"] == "R$ 183,25"

    def test_expired_promotions_never_expose_the_old_discount(self, toolbox):
        payload = call(toolbox, "get_product_details", product_id=91)
        assert payload["expired_promotions"] == ["Black Friday"]
        assert payload["pricing"]["promotion"] is None
        assert "629" not in json.dumps(payload)  # the old 30% price

    def test_out_of_stock_keeps_the_price_and_suggests_alternatives(self, toolbox):
        payload = call(toolbox, "get_product_details", product_id=96)
        assert payload["availability"] == "out_of_stock"
        assert payload["pricing"]["final_price"] == "R$ 799,90"
        assert "stock" not in payload
        assert 1 <= len(payload["alternatives"]) <= 3
        assert all(item["category"] == "Violões" for item in payload["alternatives"])

    @pytest.mark.parametrize(
        ("product_id", "status"), [(136, "discontinued"), (130, "coming_soon")]
    )
    def test_products_that_cannot_be_bought_hide_price_and_stock(self, toolbox, product_id, status):
        payload = call(toolbox, "get_product_details", product_id=product_id)
        assert payload["availability"] == status
        assert "pricing" not in payload
        assert "stock" not in payload
        assert payload["alternatives"]

    def test_unreliable_description_is_not_returned(self, toolbox):
        payload = call(toolbox, "get_product_details", product_id=137)
        assert payload["description"] is None
        assert payload["specs"]["strings"] == "4"
        assert "Ibanez" not in json.dumps(payload)

    def test_missing_product(self, toolbox):
        assert call(toolbox, "get_product_details", product_id=9999)["found"] is False


class TestGetOrder:
    def test_shipped_order_has_not_started_the_return_clock(self, toolbox):
        payload = call(toolbox, "get_order", order_id=8, contact=ANA_EMAIL)
        assert payload["verified"] is True
        assert payload["customer_first_name"] == "Ana"
        assert payload["status"] == "enviado"
        assert payload["items"] == [{"name": "Kala KA-C Concert Mogno", "quantity": 1}]
        assert payload["payment"] == "cartão de débito"
        assert payload["tracking_code"] == "BRJL5544332BR"
        assert payload["days_past_estimate"] == 25
        assert payload["return_windows"]["started"] is False

    def test_phone_also_verifies(self, toolbox):
        assert call(toolbox, "get_order", order_id=8, contact="67 99654-7821")["verified"] is True

    def test_delivered_order_reports_calculated_deadlines(self, toolbox):
        payload = call(toolbox, "get_order", order_id=7, contact="leticia.rocha@jmail.com")
        windows = payload["return_windows"]
        assert windows["started"] is True
        assert windows["assumed_received_on"] == "17/02/2026"
        assert windows["withdrawal_7_days"] == {"deadline": "24/02/2026", "open": False}
        assert windows["defect_exchange_30_days"]["open"] is False
        assert windows["legal_warranty_90_days"] == {"deadline": "18/05/2026", "open": True}
        assert "previsão de entrega" in windows["assumption"]

    @pytest.mark.parametrize(
        ("order_id", "contact", "total"),
        [
            (3, "isabela.moreira@jmail.com", "R$ 3.450,00"),
            (20, "thiago.barbosa@jmail.com", "R$ 1.400,00"),
        ],
    )
    def test_reports_the_recorded_total_even_when_items_differ(
        self, toolbox, order_id, contact, total
    ):
        assert (
            call(toolbox, "get_order", order_id=order_id, contact=contact)["recorded_total"]
            == total
        )

    def test_credit_payment_label(self, toolbox):
        payload = call(toolbox, "get_order", order_id=6, contact="gabriel.araujo@jmail.com")
        assert payload["payment"] == "cartão de crédito em 12x"

    def test_cancelled_order_shows_the_reason_and_no_windows(self, toolbox):
        payload = call(toolbox, "get_order", order_id=19, contact="pedro.oliveira@jmail.com")
        assert payload["status"] == "cancelado"
        assert "Pagamento não confirmado" in payload["notes"]
        assert "return_windows" not in payload

    def test_pending_order_has_no_tracking_or_windows(self, toolbox):
        payload = call(toolbox, "get_order", order_id=13, contact="fernanda.ribeiro@coldmail.com")
        assert payload["status"] == "pendente"
        assert payload["tracking_code"] is None
        assert "return_windows" not in payload

    def test_shared_email_only_opens_the_order_it_belongs_to(self, toolbox):
        assert call(toolbox, "get_order", order_id=10, contact="bruno.martins@jmail.com")[
            "verified"
        ]
        assert not call(toolbox, "get_order", order_id=8, contact="bruno.martins@jmail.com")[
            "verified"
        ]

    def test_missing_order_and_wrong_contact_are_indistinguishable(self, toolbox):
        wrong_contact = call(toolbox, "get_order", order_id=8, contact="x@y.com")
        missing_order = call(toolbox, "get_order", order_id=9999, contact="x@y.com")
        assert wrong_contact == missing_order
        assert wrong_contact["verified"] is False

    def test_another_customers_data_never_appears_on_failure(self, toolbox):
        payload = call(toolbox, "get_order", order_id=8, contact="x@y.com")
        assert "Ana" not in json.dumps(payload, ensure_ascii=False)

    def test_payload_exposes_no_contact_data(self, toolbox):
        text = json.dumps(call(toolbox, "get_order", order_id=8, contact=ANA_EMAIL))
        assert ANA_EMAIL not in text
        assert "99654" not in text
        assert "Ferreira" not in text

    def test_locks_after_too_many_failures(self, toolbox, store, tmp_path):
        for _ in range(MAX_FAILED_LOOKUPS):
            call(toolbox, "get_order", order_id=8, contact="x@y.com")

        locked = call(toolbox, "get_order", order_id=8, contact=ANA_EMAIL)
        assert locked["verified"] is False
        assert locked["locked"] is True

        new_conversation = Toolbox(store, now=lambda: NOW, tickets_path=tmp_path / "t.jsonl")
        assert call(new_conversation, "get_order", order_id=8, contact=ANA_EMAIL)["verified"]


class TestRegisterTicket:
    def test_complaint_is_stored_and_promises_the_manual_deadline(self, toolbox, tmp_path):
        payload = call(
            toolbox,
            "register_ticket",
            kind="reclamacao",
            summary="Instrumento chegou com a caixa amassada.",
            order_id=8,
            contact=ANA_EMAIL,
        )
        assert payload["registered"] is True
        assert payload["response_time"] == "24 horas úteis"

        stored = json.loads((tmp_path / "tickets.jsonl").read_text(encoding="utf-8"))
        assert stored["ticket_id"] == payload["ticket_id"]
        assert stored["kind"] == "reclamacao"
        assert stored["created_at"] == NOW.isoformat()

    def test_other_kinds_promise_no_deadline(self, toolbox):
        payload = call(
            toolbox, "register_ticket", kind="cancelamento", summary="Quer cancelar o pedido."
        )
        assert "response_time" not in payload

    def test_rejects_an_unknown_kind(self, toolbox):
        result = toolbox.execute("register_ticket", {"kind": "elogio", "summary": "Muito bom!"})
        assert result.is_error is True


class TestExecute:
    def test_schemas_cover_every_tool(self, toolbox):
        definitions = toolbox.definitions()
        assert {d["name"] for d in definitions} == {
            "search_products",
            "get_product_details",
            "get_order",
            "register_ticket",
        }
        for definition in definitions:
            assert definition["description"]
            assert definition["input_schema"]["type"] == "object"

    def test_unknown_tool_is_an_error_result(self, toolbox):
        result = toolbox.execute("delete_everything", {})
        assert result.is_error is True
        assert "unknown_tool" in result.content

    @pytest.mark.parametrize(
        ("name", "arguments"),
        [
            ("get_product_details", {"product_id": "abc"}),
            ("get_product_details", {}),
            ("get_order", {"order_id": 8}),
            ("get_order", {"order_id": 8, "contact": ""}),
            ("get_order", {"order_id": 8, "contact": ANA_EMAIL, "customer_id": 2}),
            ("search_products", {"query": "x", "max_price": -10}),
        ],
    )
    def test_invalid_input_never_raises(self, toolbox, name, arguments):
        result = toolbox.execute(name, arguments)
        assert result.is_error is True
        assert "invalid_input" in result.content

    def test_a_crash_inside_a_tool_becomes_an_error_result(self, store, tmp_path):
        # A directory in the ticket file's place makes open() fail.
        blocked = tmp_path / "tickets.jsonl"
        blocked.mkdir()
        toolbox = Toolbox(store, now=lambda: NOW, tickets_path=blocked)

        result = toolbox.execute("register_ticket", {"kind": "reclamacao", "summary": "Caso teste"})

        assert result.is_error is True
        assert "internal_error" in result.content
