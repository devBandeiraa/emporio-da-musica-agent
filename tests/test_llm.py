from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors, types

from emporio_agent.llm import (
    MAX_ATTEMPTS,
    GeminiClient,
    LLMAuthError,
    LLMUnavailableError,
    ToolRequest,
    tool_results_content,
    user_content,
)
from emporio_agent.tools import ToolResult

SYSTEM = "sistema"
CONTENTS = [user_content("oi")]
TOOLS = [
    {
        "name": "search_products",
        "description": "Busca produtos.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    }
]


def api_response(*parts, finish_reason=types.FinishReason.STOP, usage=None):
    candidate = types.Candidate(
        content=types.Content(role="model", parts=list(parts)), finish_reason=finish_reason
    )
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def text_part(text, **kwargs):
    return types.Part(text=text, **kwargs)


def call_part(name="search_products", call_id="call_1", **arguments):
    return types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=arguments))


def client_with(generate):
    client = GeminiClient(api_key="test", model="gemini-test")
    client._client = MagicMock()
    client._client.models.generate_content = generate
    return client


def create_with(raw):
    return client_with(MagicMock(return_value=raw)).create_message(SYSTEM, CONTENTS, TOOLS)


def test_sends_model_system_contents_and_tools():
    generate = MagicMock(return_value=api_response(text_part("oi")))

    client_with(generate).create_message(SYSTEM, CONTENTS, TOOLS)

    arguments = generate.call_args.kwargs
    assert arguments["model"] == "gemini-test"
    assert arguments["contents"] is CONTENTS
    config = arguments["config"]
    assert config.system_instruction == SYSTEM
    declaration = config.tools[0].function_declarations[0]
    assert declaration.name == "search_products"
    assert declaration.parameters_json_schema == TOOLS[0]["input_schema"]


def test_the_agent_loop_runs_the_tools_not_the_sdk():
    generate = MagicMock(return_value=api_response(text_part("oi")))
    client_with(generate).create_message(SYSTEM, CONTENTS, TOOLS)
    assert generate.call_args.kwargs["config"].automatic_function_calling.disable is True


def test_text_answer():
    response = create_with(api_response(text_part("  Olá! ")))
    assert response.stop_reason == "end_turn"
    assert response.text == "Olá!"
    assert response.tool_requests == ()


def test_function_call_becomes_a_tool_request():
    response = create_with(api_response(call_part(query="Takamine")))
    assert response.stop_reason == "tool_use"
    assert response.tool_requests == (
        ToolRequest("call_1", "search_products", {"query": "Takamine"}),
    )


def test_thought_parts_never_reach_the_customer():
    response = create_with(api_response(text_part("raciocínio", thought=True), text_part("Oi!")))
    assert response.text == "Oi!"


def test_model_turn_is_kept_with_its_thought_signature():
    part = call_part(query="x")
    part.thought_signature = b"signature"

    response = create_with(api_response(part))

    assert response.content.parts[0].thought_signature == b"signature"


@pytest.mark.parametrize(
    "finish_reason",
    [
        types.FinishReason.MAX_TOKENS,
        types.FinishReason.SAFETY,
        types.FinishReason.MALFORMED_FUNCTION_CALL,
    ],
)
def test_unfinished_answers_are_incomplete(finish_reason):
    response = create_with(api_response(text_part("Meia"), finish_reason=finish_reason))
    assert response.stop_reason == "incomplete"


def test_blocked_prompt_with_no_candidates_is_incomplete():
    assert create_with(types.GenerateContentResponse()).stop_reason == "incomplete"


def test_empty_candidate_is_an_empty_answer():
    raw = types.GenerateContentResponse(
        candidates=[types.Candidate(finish_reason=types.FinishReason.STOP)]
    )
    response = create_with(raw)
    assert response.stop_reason == "end_turn"
    assert response.text == ""


def test_tool_results_go_back_in_one_turn():
    success = ToolRequest("a", "search_products", {})
    failure = ToolRequest("b", "get_order", {})

    content = tool_results_content(
        [(success, ToolResult('{"total": 1}')), (failure, ToolResult('{"error": "x"}', True))]
    )

    first, second = [part.function_response for part in content.parts]
    assert content.role == "user"
    assert (first.id, first.name, first.response) == (
        "a",
        "search_products",
        {"output": {"total": 1}},
    )
    assert second.response == {"error": {"error": "x"}}


def test_accumulates_usage():
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100,
        candidates_token_count=20,
        thoughts_token_count=5,
        cached_content_token_count=80,
    )
    client = client_with(MagicMock(return_value=api_response(text_part("oi"), usage=usage)))

    client.create_message(SYSTEM, CONTENTS, TOOLS)
    client.create_message(SYSTEM, CONTENTS, TOOLS)

    assert client.usage == {
        "prompt_tokens": 200,
        "output_tokens": 40,
        "thinking_tokens": 10,
        "cached_tokens": 160,
        "requests": 2,
    }


def api_error(error_type, code, message):
    return error_type(code, {"error": {"code": code, "message": message, "status": "ERROR"}})


@pytest.fixture
def waits(monkeypatch):
    delays = []
    monkeypatch.setattr("emporio_agent.llm.time.sleep", delays.append)
    return delays


def test_retries_rate_limits_and_overload_then_succeeds(waits):
    generate = MagicMock(
        side_effect=[
            api_error(errors.ClientError, 429, "Quota exceeded"),
            api_error(errors.ServerError, 503, "High demand"),
            api_response(text_part("Oi!")),
        ]
    )

    response = client_with(generate).create_message(SYSTEM, CONTENTS, TOOLS)

    assert response.text == "Oi!"
    assert generate.call_count == 3
    assert waits == [2, 4]


def test_gives_up_after_the_last_attempt(waits):
    error = api_error(errors.ServerError, 503, "High demand")
    generate = MagicMock(side_effect=error)

    with pytest.raises(LLMUnavailableError):
        client_with(generate).create_message(SYSTEM, CONTENTS, TOOLS)

    assert generate.call_count == MAX_ATTEMPTS
    assert len(waits) == MAX_ATTEMPTS - 1


def test_permanent_errors_are_not_retried(waits):
    generate = MagicMock(side_effect=api_error(errors.ClientError, 403, "No permission"))

    with pytest.raises(LLMAuthError):
        client_with(generate).create_message(SYSTEM, CONTENTS, TOOLS)

    assert generate.call_count == 1
    assert waits == []


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (403, "The caller does not have permission"),
        (400, "API key not valid. Please pass a valid API key."),
    ],
)
def test_rejected_credentials_raise_auth_error(code, message):
    error = api_error(errors.ClientError, code, message)
    with pytest.raises(LLMAuthError):
        client_with(MagicMock(side_effect=error)).create_message(SYSTEM, CONTENTS, TOOLS)


@pytest.mark.parametrize(
    "error",
    [api_error(errors.ClientError, 400, "Bad request"), httpx.ConnectError("no network")],
)
def test_other_failures_raise_unavailable(error):
    with pytest.raises(LLMUnavailableError):
        client_with(MagicMock(side_effect=error)).create_message(SYSTEM, CONTENTS, TOOLS)
