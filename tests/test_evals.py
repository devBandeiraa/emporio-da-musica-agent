"""The scenario checks run on scripted conversations here, so CI needs no API key."""

import json

import pytest
from evals.runner import Transcript, check, render_markdown
from evals.scenarios import SCENARIOS, Scenario

from emporio_agent.agent import FALLBACK_REPLY, ToolCall
from emporio_agent.config import Settings
from emporio_agent.text import normalize
from emporio_agent.tools import ToolResult

TOOL_NAMES = {"search_products", "get_product_details", "get_order", "register_ticket"}


def transcript_of(scenario, reply, *calls):
    return Transcript(scenario, turns=[(scenario.turns[0], reply)], calls=[list(calls)])


def tool_call(name, payload):
    return ToolCall(name, {}, ToolResult(json.dumps(payload, ensure_ascii=False)))


def test_scenario_names_are_unique():
    names = [scenario.name for scenario in SCENARIOS]
    assert len(names) == len(set(names))


def test_scenario_texts_survive_normalization():
    # "R$" alone normalizes to "r", which would match almost any reply.
    for scenario in SCENARIOS:
        for text in scenario.must_not_include:
            assert len(normalize(text)) > 1, text


def test_scenarios_only_name_real_tools():
    for scenario in SCENARIOS:
        assert set(scenario.expected_tools + scenario.forbidden_tools) <= TOOL_NAMES


def test_publishes_between_three_and_five_examples():
    examples = [scenario.example for scenario in SCENARIOS if scenario.example]
    assert 3 <= len(examples) <= 5
    assert len(examples) == len(set(examples))


def test_passing_conversation_has_no_failures():
    scenario = Scenario("s", "t", ("Quanto custa?",), ("search_products",), must_include=("2.199",))
    call = tool_call("search_products", {"final_price": "R$ 2.199,00"})
    assert check(transcript_of(scenario, "Custa R$ 2.199,00!", call), manual="") == []


def test_reports_missing_and_forbidden_tools():
    scenario = Scenario("s", "t", ("oi",), ("get_order",), ("search_products",))
    failures = check(transcript_of(scenario, "oi", tool_call("search_products", {})), manual="")
    assert "expected tool not called: get_order" in failures
    assert "forbidden tool called: search_products" in failures


def test_text_checks_ignore_accents_and_case():
    scenario = Scenario("s", "t", ("oi",), must_include=("INDISPONÍVEL",))
    assert check(transcript_of(scenario, "está indisponivel"), manual="") == []


def test_reports_forbidden_text():
    scenario = Scenario("s", "t", ("oi",), must_not_include=("GF-3D",))
    assert check(transcript_of(scenario, "Temos o GF-3D"), manual="") == [
        "must not appear in replies: GF-3D"
    ]


def test_invented_price_fails():
    scenario = Scenario("s", "t", ("oi",))
    failures = check(transcript_of(scenario, "Custa R$ 1.999,00"), manual="")
    assert failures == ["price not backed by any source: 1999.00"]


def test_fallback_reply_fails_the_scenario():
    scenario = Scenario("s", "t", ("oi",))
    failures = check(transcript_of(scenario, FALLBACK_REPLY), manual=FALLBACK_REPLY)
    assert failures == ["agent fell back: the model gave no usable answer"]


def test_prices_are_compared_by_value():
    scenario = Scenario("s", "t", ("oi",))
    call = tool_call("get_order", {"recorded_total": "R$ 100,00"})
    assert check(transcript_of(scenario, "São R$ 100 no total", call), manual="") == []
    assert check(transcript_of(scenario, "São R$ 1.000,00 no total", call), manual="") == [
        "price not backed by any source: 1000.00"
    ]


@pytest.mark.parametrize(
    ("reply", "manual", "message"),
    [
        ("Frete de R$ 35,00", "taxa fixa de R$ 35,00", "oi"),
        ("Até R$ 1000, certo?", "", "Violões até R$1000?"),
    ],
)
def test_prices_from_the_manual_or_customer_are_accepted(reply, manual, message):
    assert check(transcript_of(Scenario("s", "t", (message,)), reply), manual) == []


def test_markdown_keeps_each_turn_with_its_tools():
    scenario = Scenario("s", "Título", ("oi",))
    call = ToolCall("get_order", {"order_id": 8}, ToolResult("{}"))

    text = render_markdown(
        transcript_of(scenario, "Olá!", call), Settings(api_key="k", model="modelo-x")
    )

    assert text.startswith("# Título")
    assert "Real agent output" in text
    assert "`modelo-x`" in text
    assert '> Tool: `get_order({"order_id": 8})`' in text
    assert text.index("**Cliente:** oi") < text.index("> Tool") < text.index("**Sol:** Olá!")
