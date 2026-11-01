"""The Claude adapter over real HTTP against a loopback server (no internet).

These use the adapter's own default SDK client, so they also prove the SDK's retries are really off.
"""

import http.server
import json
import socket
import threading
import time

import pytest
from claude_helpers import KEY, message, model, text, tool_use

from bugbite.adapter import ClaudeAdapter, GenerationRequest, Message
from bugbite.errors import BAD_RESPONSE, NETWORK_ERROR_MODEL, RATE_LIMITED_MODEL, SERVER_ERROR_MODEL, TIMEOUT_MODEL, AdapterError

REQUEST = GenerationRequest(messages=(Message.user("hello over the wire"),))


def send_json(handler, status, data, headers=None):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def error_body(kind, text="nope"):
    return {"type": "error", "error": {"type": kind, "message": text}}


@pytest.fixture
def start_server():
    servers = []

    def start(behavior):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                seen.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                             "version": self.headers.get("anthropic-version"), "type": self.headers.get("Content-Type"),
                             "body": json.loads(raw or b"{}")})  # fmt: skip
                behavior(self)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}", seen

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def adapters():
    made = []

    def make(base_url, timeout=5.0, **overrides):
        adapter = ClaudeAdapter(model(base_url=base_url, **overrides), KEY, timeout=timeout)
        made.append(adapter)
        return adapter

    yield make
    for adapter in made:
        adapter.close()


def test_round_trip_over_real_http(start_server, adapters):
    reply = message([text("hello back")], usage={"input_tokens": 9, "output_tokens": 4, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0})
    base_url, seen = start_server(lambda h: send_json(h, 200, reply, {"request-id": "req_wire_1"}))
    response = adapters(base_url).generate(REQUEST)
    assert response.text == "hello back" and response.request_id == "req_wire_1"
    assert response.usage.cache_write_tokens == 100 and response.usage.total == 113
    sent = seen[0]
    assert sent["path"] == "/v1/messages"
    assert sent["authorization"] == f"Bearer {KEY}" and sent["version"] and sent["type"] == "application/json"
    assert sent["body"]["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hello over the wire"}]}]
    assert sent["body"]["thinking"] == {"type": "disabled"} and "temperature" not in sent["body"]


def test_tool_use_over_real_http(start_server, adapters):
    reply = message([tool_use("read_file", {"path": "x.py"})], stop_reason="tool_use")
    base_url, _ = start_server(lambda h: send_json(h, 200, reply))
    (call,) = adapters(base_url).generate(REQUEST).tool_calls
    assert call.name == "read_file" and call.arguments == {"path": "x.py"}


@pytest.mark.parametrize(
    "status, body, headers, code",
    [
        (429, error_body("rate_limit_error"), {"retry-after": "4"}, RATE_LIMITED_MODEL),
        (500, error_body("api_error"), None, SERVER_ERROR_MODEL),
        (529, error_body("overloaded_error"), None, SERVER_ERROR_MODEL),
        (503, error_body("api_error"), None, SERVER_ERROR_MODEL),
    ],
)
def test_the_sdks_own_retries_are_off_so_each_failure_is_exactly_one_request(start_server, adapters, status, body, headers, code):
    # The SDK retries 429 and 5xx twice by default; if that were left on, `seen` would hold three requests.
    base_url, seen = start_server(lambda h: send_json(h, status, body, headers))
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code == code and info.value.status_code == status
    assert len(seen) == 1
    if headers:
        assert info.value.retry_after_s == 4.0


def test_a_slow_server_gives_a_timeout_and_is_not_retried(start_server, adapters):
    def slow(handler):
        time.sleep(3)
        send_json(handler, 200, message())

    base_url, seen = start_server(slow)
    started = time.monotonic()
    with pytest.raises(AdapterError) as info:
        adapters(base_url, timeout=0.5).generate(REQUEST)
    assert info.value.code == TIMEOUT_MODEL
    assert time.monotonic() - started < 2.5 and len(seen) == 1


def test_a_closed_port_gives_a_network_error(adapters):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(AdapterError) as info:
        adapters(f"http://127.0.0.1:{port}").generate(REQUEST)
    assert info.value.code == NETWORK_ERROR_MODEL and KEY not in info.value.message


def test_a_connection_dropped_mid_response_is_an_adapter_error(start_server, adapters):
    def drop(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", "5000")
        handler.end_headers()
        handler.wfile.write(b'{"id": "msg_1", "con')
        handler.wfile.flush()
        handler.close_connection = True

    base_url, seen = start_server(drop)
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code in (NETWORK_ERROR_MODEL, BAD_RESPONSE) and len(seen) == 1


def test_non_json_over_the_wire_is_a_bad_response(start_server, adapters):
    def html(handler):
        body = b"<html>gateway page</html>"
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    base_url, _ = start_server(html)
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code == BAD_RESPONSE


def test_redirects_are_not_followed_and_the_key_goes_nowhere_else(start_server, adapters):
    target_url, target_seen = start_server(lambda h: send_json(h, 200, message()))

    def redirect(handler):
        handler.send_response(307)
        handler.send_header("Location", f"{target_url}/v1/messages")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    base_url, seen = start_server(redirect)
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code == BAD_RESPONSE
    assert len(seen) == 1 and target_seen == []  # the redirect target never saw a request, or the key


def test_the_same_adapter_can_make_several_calls(start_server, adapters):
    base_url, seen = start_server(lambda h: send_json(h, 200, message([text("again")])))
    adapter = adapters(base_url)
    assert [adapter.generate(REQUEST).text for _ in range(3)] == ["again"] * 3 and len(seen) == 3


def test_unicode_survives_the_wire(start_server, adapters):
    value = "café ✓ \U0001f41b"
    base_url, seen = start_server(lambda h: send_json(h, 200, message([text(value)])))
    assert adapters(base_url).generate(GenerationRequest(messages=(Message.user(value),))).text == value
    assert seen[0]["body"]["messages"][0]["content"][0]["text"] == value
