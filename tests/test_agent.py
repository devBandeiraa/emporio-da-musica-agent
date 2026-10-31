import json
from datetime import datetime

import pytest

from emporio_agent.agent import FALLBACK_REPLY, MAX_TOOL_ROUNDS, Agent, build_agent
from emporio_agent.config import Settings
from emporio_agent.llm import AnthropicClient, LLMAuthError, LLMUnavailableError
from emporio_agent.tools import Toolbox
from tests.conftest import DATA_DIR
from tests.fakes import FakeLLM, calls, response, says, text_block, tool_block

NOW = datetime(2026, 3, 25, 10, 0)


@pytest.fixture
def toolbox(store, tmp_path):
    return Toolbox(store, now=lambda: NOW, tickets_path=tmp_path / "tickets.jsonl")


def make_agent(toolbox, llm, **kwargs):
    return Agent(llm, toolbox, NOW, **kwargs)


def tool_results(request):
    return request.messages[-1]["content"]


def test_returns_the_model_text(toolbox):
    llm = FakeLLM(says("Oi! Como posso ajudar?"))
    assert make_agent(toolbox, llm).reply("oi") == "Oi! Como posso ajudar?"


def test_sends_system_tools_and_user_message(toolbox):
    llm = FakeLLM(says("Oi!"))
    make_agent(toolbox, llm).reply("oi")

    request = llm.requests[0]
    assert "Sol" in request.system[0]["text"]
    assert len(request.tools) == 4
    assert request.messages == [{"role": "user", "content": "oi"}]


def test_runs_a_tool_and_feeds_the_result_back(toolbox):
    llm = FakeLLM(
        calls(tool_block("search_products", query="Takamine GD20")),
        says("Custa R$ 2.199,00!"),
    )

    answer = make_agent(toolbox, llm).reply("Quanto custa o Takamine GD20?")

    assert answer == "Custa R$ 2.199,00!"
    result = tool_results(llm.requests[1])[0]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "call_1"
    assert result["is_error"] is False
    assert json.loads(result["content"])["results"][0]["product_id"] == 95


def test_keeps_assistant_content_unchanged_in_history(toolbox):
    tool_response = calls(tool_block("get_product_details", product_id=95))
    llm = FakeLLM(tool_response, says("Pronto."))

    make_agent(toolbox, llm).reply("detalhes")

    assert llm.requests[1].messages[1] == {"role": "assistant", "content": tool_response.content}


def test_parallel_calls_return_in_a_single_message(toolbox):
    llm = FakeLLM(
        calls(
            tool_block("get_product_details", block_id="a", product_id=94),
            tool_block("get_product_details", block_id="b", product_id=95),
        ),
        says("Comparei os dois."),
    )

    make_agent(toolbox, llm).reply("compare")

    results = tool_results(llm.requests[1])
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert len(llm.requests[1].messages) == 3


def test_chains_tools_across_rounds(toolbox):
    llm = FakeLLM(
        calls(tool_block("search_products", query="Taylor 110e")),
        calls(tool_block("get_product_details", product_id=94)),
        says("Tem promoção de 8%."),
    )

    assert make_agent(toolbox, llm).reply("Taylor 110e com desconto?") == "Tem promoção de 8%."
    assert "R$ 5.519,08" in tool_results(llm.requests[2])[0]["content"]


def test_ignores_preamble_text_next_to_a_tool_call(toolbox):
    llm = FakeLLM(
        response(
            text_block("Vou olhar."),
            tool_block("get_product_details", product_id=95),
            stop_reason="tool_use",
        ),
        says("Achei."),
    )
    assert make_agent(toolbox, llm).reply("olha") == "Achei."


def test_invalid_tool_input_reaches_the_model_as_an_error(toolbox):
    llm = FakeLLM(
        calls(tool_block("get_product_details", product_id="abc")),
        says("Não achei esse produto."),
    )

    make_agent(toolbox, llm).reply("produto abc")

    result = tool_results(llm.requests[1])[0]
    assert result["is_error"] is True
    assert "invalid_input" in result["content"]


def test_unknown_tool_does_not_break_the_conversation(toolbox):
    llm = FakeLLM(calls(tool_block("apagar_tudo")), says("Não posso fazer isso."))
    assert make_agent(toolbox, llm).reply("apague tudo") == "Não posso fazer isso."


def test_keeps_history_across_turns(toolbox):
    llm = FakeLLM(says("Oi!"), says("Claro."))
    agent = make_agent(toolbox, llm)

    agent.reply("oi")
    agent.reply("tudo bem?")

    roles = [message["role"] for message in llm.requests[1].messages]
    assert roles == ["user", "assistant", "user"]


def test_reports_tool_calls_to_the_observer(toolbox):
    seen = []
    llm = FakeLLM(calls(tool_block("get_product_details", product_id=95)), says("Ok."))

    make_agent(toolbox, llm, on_tool_call=seen.append).reply("detalhes")

    assert seen[0].name == "get_product_details"
    assert seen[0].arguments == {"product_id": 95}
    assert seen[0].result.is_error is False


def test_contact_is_verified_by_the_tool_not_by_the_model(toolbox):
    llm = FakeLLM(
        calls(tool_block("get_order", order_id=8, contact="golpista@exemplo.com")),
        says("Não consegui confirmar."),
    )

    make_agent(toolbox, llm).reply("pedido 8, meu e-mail é golpista@exemplo.com")

    content = tool_results(llm.requests[1])[0]["content"]
    assert json.loads(content)["verified"] is False
    assert "Kala" not in content


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens", "pause_turn"])
def test_incomplete_responses_become_the_fallback_reply(toolbox, stop_reason):
    llm = FakeLLM(response(text_block("Meia resp"), stop_reason=stop_reason))
    assert make_agent(toolbox, llm).reply("oi") == FALLBACK_REPLY


def test_refused_turn_leaves_history_clean(toolbox):
    llm = FakeLLM(says("Oi!"), response(stop_reason="refusal"), says("Tudo certo."))
    agent = make_agent(toolbox, llm)

    agent.reply("oi")
    assert agent.reply("mensagem recusada") == FALLBACK_REPLY
    assert agent.reply("vamos de novo") == "Tudo certo."

    contents = [m["content"] for m in llm.requests[2].messages if m["role"] == "user"]
    assert contents == ["oi", "vamos de novo"]


def test_truncated_tool_call_is_not_left_in_history(toolbox):
    truncated = response(tool_block("get_product_details", product_id=95), stop_reason="max_tokens")
    llm = FakeLLM(truncated, says("Agora foi."))
    agent = make_agent(toolbox, llm)

    assert agent.reply("oi") == FALLBACK_REPLY
    assert agent.reply("de novo") == "Agora foi."
    assert llm.requests[1].messages == [{"role": "user", "content": "de novo"}]


def test_empty_answer_becomes_the_fallback_reply(toolbox):
    llm = FakeLLM(response())
    assert make_agent(toolbox, llm).reply("oi") == FALLBACK_REPLY


def test_stops_after_too_many_tool_rounds(toolbox):
    llm = FakeLLM(
        *[calls(tool_block("get_product_details", product_id=95)) for _ in range(MAX_TOOL_ROUNDS)]
    )

    assert make_agent(toolbox, llm).reply("loop") == FALLBACK_REPLY
    assert len(llm.requests) == MAX_TOOL_ROUNDS


def test_api_outage_becomes_the_fallback_reply_and_recovers(toolbox):
    llm = FakeLLM(LLMUnavailableError("timeout"), says("Voltei."))
    agent = make_agent(toolbox, llm)

    assert agent.reply("oi") == FALLBACK_REPLY
    assert agent.reply("oi de novo") == "Voltei."


def test_build_agent_wires_the_real_components(tmp_path):
    settings = Settings(
        api_key="test",
        reference_datetime=NOW,
        data_dir=DATA_DIR,
        tickets_path=tmp_path / "tickets.jsonl",
    )

    agent, llm = build_agent(settings)

    assert isinstance(agent, Agent)
    assert isinstance(llm, AnthropicClient)


def test_rejected_api_key_is_not_hidden(toolbox):
    llm = FakeLLM(LLMAuthError("invalid key"))
    with pytest.raises(LLMAuthError):
        make_agent(toolbox, llm).reply("oi")
