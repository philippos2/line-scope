"""Prototype Ollama native chat adapter; no provider bodies or thinking are logged."""

import http.client
import math
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from ..domain.canonical import canonical_json, strict_json


class LLMError(Exception):
    """Provider failure; the caller translates it into its public error contract."""

    def __init__(self, code, message, *, metrics=()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.metrics = metrics


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class LLMReply:
    content: str
    tool_calls: tuple[ToolCall, ...]
    metrics: tuple[tuple[str, int | str], ...] = ()

    def assistant_message(self):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments, "index": index},
                }
                for index, call in enumerate(self.tool_calls)
            ],
        }


def provider_metrics(data):
    metrics = []
    for source, name, divisor in (
        ("prompt_eval_count", "llm_prompt_tokens", 1),
        ("eval_count", "llm_generated_tokens", 1),
        ("prompt_eval_duration", "llm_prompt_ms", 1000000),
        ("eval_duration", "llm_generate_ms", 1000000),
        ("load_duration", "llm_load_ms", 1000000),
    ):
        value = data.get(source)
        if type(value) is int and 0 <= value <= 2**63 - 1:
            metrics.append((name, value // divisor))
    reason = data.get("done_reason")
    metrics.append(
        (
            "llm_finish_reason",
            {"stop": "STOP", "length": "LENGTH"}.get(reason, "OTHER")
            if type(reason) is str
            else "OTHER",
        )
    )
    message = data.get("message")
    if type(message) is dict:
        for key, field in (("content", "llm_content_chars"), ("thinking", "llm_thinking_chars")):
            if type(message.get(key)) is str:
                metrics.append((field, len(message[key])))
    return tuple(metrics)


def parse_reply(body, schemas):
    metrics = ()
    try:
        data = strict_json(body)
        if type(data) is dict:
            metrics = provider_metrics(data)
        if (
            type(data) is not dict
            or data.get("done") is not True
            or data.get("done_reason") != "stop"
        ):
            raise ValueError("Incomplete reply")
        message = data["message"]
        if type(message) is not dict or message.get("role") != "assistant":
            raise ValueError("Assistant reply is required")
        content = message.get("content", "")
        if (
            type(content) is not str
            or len(content) > 32000
            or "<think>" in content.lower()
            or "</think>" in content.lower()
        ):
            raise ValueError("Invalid public content")
        calls = message.get("tool_calls", [])
        if type(calls) is not list or len(calls) > 12:
            raise ValueError("Invalid Tool calls")
        parsed = []
        for index, call in enumerate(calls):
            if type(call) is not dict or call.get("type", "function") != "function":
                raise ValueError("Invalid Tool call")
            function = call["function"]
            if type(function) is not dict or function.get("name") not in schemas:
                raise ValueError("Unadvertised Tool")
            if "index" in function and (
                type(function["index"]) is not int or function["index"] != index
            ):
                raise ValueError("Invalid Tool order")
            arguments = function["arguments"]
            if type(arguments) is not dict or len(canonical_json(arguments).encode("utf-8")) > 8000:
                raise ValueError("Invalid Tool arguments")
            parsed.append(ToolCall(str(uuid4()), function["name"], arguments))
        return LLMReply(content, tuple(parsed), tuple(metrics))
    except (ValueError, TypeError, KeyError) as error:
        raise LLMError(
            "INTERNAL_ERROR", "LLM returned an invalid response", metrics=metrics
        ) from error


class OllamaClient:
    def __init__(
        self, *, base_url, model, max_response_bytes=262144, context_tokens=16384, clock=monotonic
    ):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("A plain Ollama server URL is required")
        if type(model) is not str or not model.strip():
            raise ValueError("An explicit model is required")
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("Response limit must be a positive integer")
        if type(context_tokens) is not int or context_tokens <= 0:
            raise ValueError("Context tokens must be a positive integer")
        self.context_tokens = context_tokens
        self.url, self.model, self.max_response_bytes, self.clock = (
            url,
            model,
            max_response_bytes,
            clock,
        )

    def complete(self, messages, *, schemas, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("An absolute monotonic deadline is required")

        def remaining():
            value = deadline - self.clock()
            if value <= 0:
                raise LLMError("AGENT_LIMIT_REACHED", "Agent execution budget was exhausted")
            return value

        payload = canonical_json(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": 0, "num_ctx": self.context_tokens, "num_predict": 700},
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": schema.get("description", name),
                            "parameters": schema,
                        },
                    }
                    for name, schema in schemas.items()
                ],
            }
        ).encode("utf-8")
        cls = (
            http.client.HTTPSConnection
            if self.url.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = cls(self.url.hostname, self.url.port, timeout=remaining())
        try:
            connection.request("POST", "/api/chat", payload, {"Content-Type": "application/json"})
            transport_socket = connection.sock
            if transport_socket is not None:
                transport_socket.settimeout(remaining())
            response = connection.getresponse()
            if response.status != 200:
                raise LLMError("DEPENDENCY_UNAVAILABLE", "LLM service is unavailable")
            chunks = bytearray()
            while not response.isclosed():
                if transport_socket is not None:
                    transport_socket.settimeout(remaining())
                else:
                    remaining()
                part = response.read1(min(65536, self.max_response_bytes + 1 - len(chunks)))
                chunks.extend(part)
                if len(chunks) > self.max_response_bytes:
                    raise LLMError("INTERNAL_ERROR", "LLM response exceeded the size limit")
                if not part:
                    break
            remaining()
            return parse_reply(bytes(chunks), schemas)
        except TimeoutError:
            raise LLMError(
                "AGENT_LIMIT_REACHED", "LLM request exceeded the execution budget"
            ) from None
        except (OSError, http.client.HTTPException):
            raise LLMError("DEPENDENCY_UNAVAILABLE", "LLM service is unavailable") from None
        finally:
            connection.close()
