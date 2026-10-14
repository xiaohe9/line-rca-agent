"""OpenAI-compatible chat provider.

DeepSeek, OpenAI, vLLM, LM Studio and Ollama's OpenAI shim all speak the same shape, so one
adapter covers all of them; what differs is the base URL, the key and the model name.

Two things this deliberately does not do, and both are stated rather than assumed:

* **it does not retry.** A rate limit or a transient 502 surfaces as an error. Retry is a
  policy decision — how many times, with what backoff, and whether a half-finished run should
  resume — and it belongs in one place with tests, not quietly inside the transport.
* **it does not repair malformed tool arguments.** A model does occasionally emit invalid
  JSON. Swallowing it into `{}` would make the tool report "missing required field", which
  looks like the model's fault when it is actually a parsing failure this layer hid. The raw
  text goes into the error so the trace shows what arrived.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from line_rca_agent.contracts import Completion, Message, ToolCall

DEFAULT_TIMEOUT_SECONDS = 60.0


class ProviderError(RuntimeError):
    """The provider could not produce a usable completion."""


def to_openai_tools(schemas: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the kernel's MCP-shaped tool descriptors into OpenAI's function shape.

    The kernel advertises `{"name", "description", "inputSchema"}`; OpenAI wants the schema
    nested under `function.parameters`. Keeping the kernel's shape framework-neutral and doing
    the translation here is the whole point of the adapter.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for schema in schemas
    ]


def to_openai_messages(messages: Sequence[Message]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def parse_completion(payload: dict[str, Any]) -> Completion:
    """Read one chat completion. Raises rather than guessing when the shape is wrong."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(f"response carried no choices: {json.dumps(payload)[:400]}")

    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError(f"choice was not an object: {json.dumps(first)[:200]}")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderError(f"choice carried no message: {json.dumps(first)[:200]}")

    raw_content = message.get("content")
    content = raw_content if isinstance(raw_content, str) else ""

    calls: list[ToolCall] = []
    for raw_call in message.get("tool_calls") or []:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue

        raw_arguments = function.get("arguments")
        if raw_arguments is None or raw_arguments == "":
            raw_arguments = "{}"
        if not isinstance(raw_arguments, str):
            raise ProviderError(
                f"tool '{name}' arguments were {type(raw_arguments).__name__}, "
                "expected a JSON string"
            )
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"tool '{name}' returned arguments that are not valid JSON: {raw_arguments!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"tool '{name}' arguments must be a JSON object, got {type(parsed).__name__}"
            )
        calls.append(ToolCall(name=name, arguments=parsed))

    return Completion(content=content, tool_calls=tuple(calls))


class OpenAiCompatProvider:
    """An async chat provider over `POST {base_url}/chat/completions`."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        name: str = "openai-compat",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._name = name
        self._timeout = timeout
        self._transport = transport

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def request_body(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(messages),
            # Root-cause analysis wants the same answer twice, not a different one. Sampling
            # temperature would make a run unreproducible, which defeats the trace.
            "temperature": 0,
        }
        if tools:
            body["tools"] = to_openai_tools(tools)
            body["tool_choice"] = "auto"
        return body

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] = (),
    ) -> Completion:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=self.request_body(messages, tools),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {type(exc).__name__}: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name} returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise ProviderError(
                f"{self.name} returned {type(payload).__name__}, expected an object"
            )
        return parse_completion(payload)
