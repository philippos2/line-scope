import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import monotonic

import pytest

from linescope.llm import LLMError, OllamaClient, parse_reply

SCHEMAS = {"get_equipment": {"type": "object"}}


def body(**changes):
    return json.dumps(
        {
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": "fact"},
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"done": False},
        {"done": 1},
        {"done_reason": "length"},
        {"message": {"role": "user", "content": "x"}},
        {"message": {"role": "assistant", "content": "<think>private</think>"}},
        {"message": {"role": "assistant", "content": 1}},
        {"message": {"role": "assistant", "tool_calls": None}},
        {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {"type": "function", "function": {"name": "execute", "arguments": {}}}
                ],
            }
        },
    ],
)
def test_invalid_provider_reply_is_sanitized(changes):
    with pytest.raises(LLMError) as error:
        parse_reply(body(**changes), SCHEMAS)
    assert error.value.code == "INTERNAL_ERROR"
    assert error.value.message == "LLM returned an invalid response"


def test_reasoning_dropped_and_tool_arguments_retained():
    raw = body(
        message={
            "role": "assistant",
            "content": "",
            "thinking": "secret",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_equipment",
                        "arguments": {"equipment_id": "id"},
                        "index": 0,
                    },
                }
            ],
        }
    )
    reply = parse_reply(raw, SCHEMAS)
    assert reply.tool_calls[0].arguments == {"equipment_id": "id"}
    assert "secret" not in repr(reply) and "thinking" not in reply.assistant_message()
    assert reply.assistant_message()["tool_calls"][0]["function"]["index"] == 0


@pytest.mark.parametrize("arguments", [None, [], "{}", {"v": 1.5}, {"v": "x" * 8001}])
def test_malformed_arguments_rejected(arguments):
    raw = body(
        message={
            "role": "assistant",
            "tool_calls": [
                {"type": "function", "function": {"name": "get_equipment", "arguments": arguments}}
            ],
        }
    )
    with pytest.raises(LLMError):
        parse_reply(raw, SCHEMAS)


@pytest.mark.parametrize("raw", ['{"done":true,"done":false}', "{}", "[]", "\ud800", "invalid"])
def test_invalid_json(raw):
    with pytest.raises(LLMError):
        parse_reply(raw, SCHEMAS)


@pytest.fixture
def provider():
    state = {"status": 200, "body": body().encode(), "request": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["request"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_http_payload_and_reply(provider):
    url, state = provider
    reply = OllamaClient(base_url=url, model="candidate").complete(
        [{"role": "user", "content": "query"}], schemas=SCHEMAS, deadline=monotonic() + 5
    )
    assert reply.content == "fact"
    assert state["request"]["stream"] is False
    assert state["request"]["think"] is False
    assert state["request"]["tools"][0]["function"]["name"] == "get_equipment"


@pytest.mark.parametrize("status", [301, 400, 500])
def test_http_errors_do_not_expose_body(provider, status):
    url, state = provider
    state.update(status=status, body=b"private password")
    with pytest.raises(LLMError) as error:
        OllamaClient(base_url=url, model="candidate").complete(
            [], schemas={}, deadline=monotonic() + 5
        )
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "private" not in str(error.value)


def test_response_size_and_expired_deadline(provider):
    url, state = provider
    client = OllamaClient(base_url=url, model="candidate", max_response_bytes=10)
    with pytest.raises(LLMError) as error:
        client.complete([], schemas={}, deadline=monotonic() + 5)
    assert error.value.code == "INTERNAL_ERROR"
    with pytest.raises(LLMError) as error:
        client.complete([], schemas={}, deadline=monotonic() - 1)
    assert error.value.code == "AGENT_LIMIT_REACHED"


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/x",
        "http://user:secret@localhost",
        "http://localhost/path",
        "http://localhost?x=1",
    ],
)
def test_invalid_provider_configuration(url):
    with pytest.raises(ValueError):
        OllamaClient(base_url=url, model="candidate")


@pytest.mark.parametrize(
    "calls",
    [
        [
            {
                "type": "function",
                "function": {"name": "get_equipment", "arguments": {}, "index": True},
            }
        ],
        [{"type": "function", "function": {"name": "get_equipment", "arguments": {}, "index": 2}}],
        [{"type": "function", "function": {"name": "get_equipment", "arguments": {}}}] * 13,
    ],
)
def test_invalid_tool_order_and_excess_calls(calls):
    with pytest.raises(LLMError):
        parse_reply(
            body(message={"role": "assistant", "content": "", "tool_calls": calls}), SCHEMAS
        )


def test_duplicate_arguments_and_oversized_content():
    raw = '{"done":true,"done_reason":"stop","message":{"role":"assistant","tool_calls":[{"type":"function","function":{"name":"get_equipment","arguments":{"id":1,"id":2}}}]}}'
    with pytest.raises(LLMError):
        parse_reply(raw, SCHEMAS)
    with pytest.raises(LLMError):
        parse_reply(body(message={"role": "assistant", "content": "x" * 32001}), SCHEMAS)


@pytest.mark.parametrize(
    "error_class,code", [(OSError, "DEPENDENCY_UNAVAILABLE"), (TimeoutError, "AGENT_LIMIT_REACHED")]
)
def test_connection_failure_is_sanitized(monkeypatch, error_class, code):
    import http.client

    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise error_class("private host credential")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Broken)
    with pytest.raises(LLMError) as error:
        OllamaClient(base_url="http://localhost:11434", model="candidate").complete(
            [], schemas={}, deadline=monotonic() + 5
        )
    assert error.value.code == code
    assert "private" not in str(error.value)


def test_native_ollama_tool_call_without_type_is_supported():
    raw = body(
        message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "provider-id",
                    "function": {"name": "get_equipment", "arguments": {}, "index": 0},
                }
            ],
        }
    )
    reply = parse_reply(raw, SCHEMAS)
    assert reply.tool_calls[0].name == "get_equipment"
    assert reply.tool_calls[0].call_id != "provider-id"


def test_explicit_wrong_call_type_is_rejected():
    raw = body(
        message={
            "role": "assistant",
            "tool_calls": [
                {"type": "execute", "function": {"name": "get_equipment", "arguments": {}}}
            ],
        }
    )
    with pytest.raises(LLMError):
        parse_reply(raw, SCHEMAS)
