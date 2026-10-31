from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from emporio_agent.llm import (
    SERVER_FALLBACK_BETA,
    AnthropicClient,
    LLMAuthError,
    LLMUnavailableError,
)

SYSTEM = [{"type": "text", "text": "sistema"}]
MESSAGES = [{"role": "user", "content": "oi"}]
TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


def client_with(create, model="claude-opus-5-5"):
    client = AnthropicClient(api_key="test", model=model, effort="low")
    client._client = MagicMock()
    client._client.beta.messages.create = create
    return client


def api_response():
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=None,
        )
    )


def sent_arguments(model):
    create = MagicMock(return_value=api_response())
    client_with(create, model).create_message(SYSTEM, MESSAGES, TOOLS)
    return create.call_args.kwargs


def test_sends_model_effort_cache_and_content():
    arguments = sent_arguments("claude-opus-5-5")
    assert arguments["model"] == "claude-opus-5-5"
    assert arguments["output_config"] == {"effort": "low"}
    assert arguments["cache_control"] == {"type": "ephemeral"}
    assert arguments["system"] is SYSTEM
    assert arguments["messages"] is MESSAGES
    assert arguments["tools"] is TOOLS


def test_never_sends_sampling_parameters():
    assert not {"temperature", "top_p", "top_k"} & sent_arguments("claude-opus-5-5").keys()


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_enables_server_fallback_where_supported(model):
    arguments = sent_arguments(model)
    assert arguments["fallbacks"] == "default"
    assert arguments["betas"] == [SERVER_FALLBACK_BETA]


def test_skips_server_fallback_elsewhere():
    arguments = sent_arguments("claude-haiku-5-5")
    assert "fallbacks" not in arguments
    assert "betas" not in arguments


def test_accumulates_usage():
    client = client_with(MagicMock(return_value=api_response()))
    client.create_message(SYSTEM, MESSAGES, TOOLS)
    client.create_message(SYSTEM, MESSAGES, TOOLS)

    assert client.usage["input_tokens"] == 20
    assert client.usage["output_tokens"] == 10
    assert client.usage["cache_read_input_tokens"] == 200
    assert client.usage["cache_creation_input_tokens"] == 0


@pytest.mark.parametrize(
    "error_type", [anthropic.AuthenticationError, anthropic.PermissionDeniedError]
)
def test_rejected_credentials_raise_auth_error(error_type):
    error = error_type("denied", response=MagicMock(), body=None)
    with pytest.raises(LLMAuthError):
        client_with(MagicMock(side_effect=error)).create_message(SYSTEM, MESSAGES, TOOLS)


def test_other_api_errors_raise_unavailable():
    error = anthropic.APIConnectionError(request=MagicMock())
    with pytest.raises(LLMUnavailableError):
        client_with(MagicMock(side_effect=error)).create_message(SYSTEM, MESSAGES, TOOLS)
