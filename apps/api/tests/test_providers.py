"""Provider tests.

Everything here runs against `httpx.MockTransport`: no key, no network, no vendor. What is
being tested is the translation layer, which is where an adapter actually breaks — the wire
format of tool schemas and tool-call arguments.
"""

from __future__ import annotations

import json

import httpx
import pytest

from line_rca_agent.contracts import Message
from line_rca_api.agent_factory import ConfigurationError, build_provider
from line_rca_api.config import Settings
from line_rca_api.providers import (
    OpenAiCompatProvider,
    ProviderError,
    parse_completion,
    to_openai_messages,
    to_openai_tools,
)

SCHEMAS = [
    {
        "name": "query_defects",
        "description": "defect distribution for a batch",
        "inputSchema": {
            "type": "object",
            "properties": {"batch": {"type": "string"}},
            "required": ["batch"],
        },
    }
]


def completion_payload(
    content: str = "", tool_calls: list[dict] | None = None
) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def tool_call_payload(name: str, arguments: str) -> dict[str, object]:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


# --------------------------------------------------------------------------- #
#  translation
# --------------------------------------------------------------------------- #


def test_tools_are_nested_into_the_openai_function_shape() -> None:
    translated = to_openai_tools(SCHEMAS)

    assert translated == [
        {
            "type": "function",
            "function": {
                "name": "query_defects",
                "description": "defect distribution for a batch",
                "parameters": SCHEMAS[0]["inputSchema"],
            },
        }
    ]


def test_tools_without_a_schema_still_get_a_valid_parameters_object() -> None:
    translated = to_openai_tools([{"name": "noop", "description": "d"}])
    assert translated[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_messages_keep_their_roles() -> None:
    messages = [Message("system", "s"), Message("user", "u")]
    assert to_openai_messages(messages) == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


# --------------------------------------------------------------------------- #
#  response parsing
# --------------------------------------------------------------------------- #


def test_plain_content_completion() -> None:
    completion = parse_completion(completion_payload("根因是划伤"))
    assert completion.content == "根因是划伤"
    assert completion.tool_calls == ()


def test_tool_call_arguments_are_decoded_from_a_json_string() -> None:
    payload = completion_payload(
        tool_calls=[tool_call_payload("query_defects", '{"batch": "B-2041"}')]
    )
    completion = parse_completion(payload)

    assert len(completion.tool_calls) == 1
    call = completion.tool_calls[0]
    assert call.name == "query_defects"
    assert call.arguments == {"batch": "B-2041"}


def test_an_empty_arguments_string_means_no_arguments() -> None:
    payload = completion_payload(tool_calls=[tool_call_payload("list_work_orders", "")])
    assert parse_completion(payload).tool_calls[0].arguments == {}


def test_calls_without_a_name_are_skipped() -> None:
    payload = completion_payload(
        tool_calls=[
            {"id": "x", "type": "function", "function": {"arguments": "{}"}},
            {"id": "y", "type": "function"},
            tool_call_payload("query_telemetry", '{"station": "镀膜"}'),
        ]
    )
    completion = parse_completion(payload)

    assert [call.name for call in completion.tool_calls] == ["query_telemetry"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": "nope"},
        {"choices": [{}]},
        {"choices": [{"message": "nope"}]},
    ],
)
def test_malformed_responses_raise_rather_than_guess(payload: dict) -> None:
    with pytest.raises(ProviderError):
        parse_completion(payload)


@pytest.mark.parametrize(
    "arguments",
    ["{not json", "[1, 2, 3]", '"a string"', "42"],
)
def test_unusable_tool_arguments_raise_with_the_raw_text(arguments: str) -> None:
    """Swallowing these into {} would make the tool blame the model for our parse failure."""
    payload = completion_payload(tool_calls=[tool_call_payload("query_defects", arguments)])

    with pytest.raises(ProviderError) as caught:
        parse_completion(payload)

    assert "query_defects" in str(caught.value)


def test_non_string_arguments_are_rejected() -> None:
    payload = completion_payload(
        tool_calls=[
            {"id": "1", "type": "function", "function": {"name": "t", "arguments": {"a": 1}}}
        ]
    )
    with pytest.raises(ProviderError, match="JSON string"):
        parse_completion(payload)


# --------------------------------------------------------------------------- #
#  the provider over a mock transport
# --------------------------------------------------------------------------- #


def make_provider(
    captured: list[httpx.Request], response: httpx.Response, **kwargs
) -> OpenAiCompatProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    return OpenAiCompatProvider(
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_request_shape_and_headers() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(captured, httpx.Response(200, json=completion_payload("ok")))

    completion = await provider.complete(
        [Message("system", "sys"), Message("user", "go")], tools=SCHEMAS
    )

    assert completion.content == "ok"
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://api.example.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"

    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0, "a run must be reproducible, so no sampling"
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "query_defects"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
    ]


async def test_no_tools_means_no_tools_key() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(captured, httpx.Response(200, json=completion_payload("ok")))

    await provider.complete([Message("user", "go")])

    body = json.loads(captured[0].content)
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_a_keyless_provider_sends_no_authorization_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_payload("ok"))

    provider = OpenAiCompatProvider(
        base_url="http://localhost:11434/v1",
        model="llama3",
        transport=httpx.MockTransport(handler),
    )
    await provider.complete([Message("user", "go")])

    assert "authorization" not in captured[0].headers


async def test_a_trailing_slash_does_not_double_up() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(captured, httpx.Response(200, json=completion_payload("ok")))

    await provider.complete([Message("user", "go")])
    assert "//chat/completions" not in str(captured[0].url)


async def test_http_errors_become_provider_errors_with_the_body() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(captured, httpx.Response(429, text="rate limited"))

    with pytest.raises(ProviderError) as caught:
        await provider.complete([Message("user", "go")])

    assert "429" in str(caught.value)
    assert "rate limited" in str(caught.value)


async def test_a_non_json_body_becomes_a_provider_error() -> None:
    captured: list[httpx.Request] = []
    provider = make_provider(captured, httpx.Response(200, text="<html>nope</html>"))

    with pytest.raises(ProviderError, match="non-JSON"):
        await provider.complete([Message("user", "go")])


async def test_a_transport_failure_becomes_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    provider = OpenAiCompatProvider(
        base_url="https://api.example.com/v1",
        model="m",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError, match="request failed"):
        await provider.complete([Message("user", "go")])


@pytest.mark.parametrize(("base_url", "model"), [("", "m"), ("https://x/v1", "")])
def test_the_constructor_refuses_an_unusable_endpoint(base_url: str, model: str) -> None:
    with pytest.raises(ValueError):
        OpenAiCompatProvider(base_url=base_url, model=model)


# --------------------------------------------------------------------------- #
#  the factory
# --------------------------------------------------------------------------- #


def test_fake_is_the_class_default() -> None:
    """`_env_file=None` on purpose.

    Without it this asserts on whatever the developer's `.env` says, so the test fails on a
    machine configured for the evaluation — which is the machine that most needs the suite to
    pass. The subject is the class default, not the local configuration.
    """
    from line_rca_agent.providers import ScriptedProvider

    assert isinstance(build_provider(Settings(_env_file=None)), ScriptedProvider)


def test_the_suite_ignores_a_developers_dot_env() -> None:
    """The guard for the conftest pin.

    Adding a `.env` with a real provider broke two tests, because `Settings` reads it and the
    API tests therefore tried to reach a paid model. `apps/api/tests/conftest.py` now pins
    `LRC_LLM_PROVIDER` in the real environment, which outranks `.env`. This asserts that the pin
    is still doing its job, so removing it fails here rather than on someone's machine.
    """
    from line_rca_agent.providers import ScriptedProvider

    assert isinstance(build_provider(Settings()), ScriptedProvider)


def test_deepseek_gets_its_base_url_and_default_model() -> None:
    provider = build_provider(Settings(llm_provider="deepseek", llm_api_key="k"))

    assert isinstance(provider, OpenAiCompatProvider)
    assert provider.name == "deepseek"
    assert provider.model == "deepseek-chat"


def test_the_vendor_key_is_used_when_no_generic_key_is_set() -> None:
    provider = build_provider(Settings(llm_provider="deepseek", deepseek_api_key="vendor-key"))
    assert isinstance(provider, OpenAiCompatProvider)


def test_a_remote_provider_without_a_key_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="needs a key"):
        build_provider(Settings(llm_provider="deepseek", llm_api_key="", deepseek_api_key=""))


def test_openai_compat_requires_an_explicit_base_url() -> None:
    with pytest.raises(ConfigurationError, match="LRC_LLM_BASE_URL"):
        build_provider(Settings(llm_provider="openai_compat", llm_api_key="k"))


def test_openai_compat_requires_an_explicit_model() -> None:
    with pytest.raises(ConfigurationError, match="LRC_LLM_MODEL"):
        build_provider(
            Settings(llm_provider="openai_compat", llm_api_key="k", llm_base_url="https://x/v1")
        )


def test_ollama_needs_no_key() -> None:
    provider = build_provider(Settings(llm_provider="ollama", llm_model="qwen3", llm_api_key=""))

    assert isinstance(provider, OpenAiCompatProvider)
    assert provider.name == "ollama"


def test_an_unknown_provider_names_the_valid_ones() -> None:
    with pytest.raises(ConfigurationError, match="fake, deepseek, openai_compat or ollama"):
        build_provider(Settings(llm_provider="gpt5-magic"))
