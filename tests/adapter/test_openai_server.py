"""The adapter over real HTTP, against a small server on the loopback interface (no internet)."""

import http.server
import json
import socket
import threading
import time

import httpx
import pytest
from openai_helpers import KEY, completion, model, tool_call

from bugbite.adapter import GenerationRequest, Message, OpenAICompatibleAdapter
from bugbite.errors import BAD_RESPONSE, NETWORK_ERROR_MODEL, RATE_LIMITED_MODEL, TIMEOUT_MODEL, AdapterError

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
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                seen.append(
                    {"path": self.path, "authorization": self.headers.get("Authorization"), "body": json.loads(raw or b"{}")}
                )
                behavior(self)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/v1", seen

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def adapters():
    made = []

    def make(base_url, key=KEY, timeout=5.0):
        adapter = OpenAICompatibleAdapter(model(base_url=base_url), key, timeout=timeout)
        made.append(adapter)
        return adapter

    yield make
    for adapter in made:
        adapter.close()


def test_round_trip_over_real_http(start_server, adapters):
    base_url, seen = start_server(lambda h: send_json(h, 200, completion("hello back")))
    response = adapters(base_url).generate(REQUEST)
    assert response.text == "hello back" and response.usage.total == 26
    assert seen[0]["path"] == "/v1/chat/completions"
    assert seen[0]["authorization"] == f"Bearer {KEY}"
    assert seen[0]["body"]["messages"] == [{"role": "user", "content": "hello over the wire"}]


def test_no_authorization_header_is_sent_without_a_key(start_server, adapters):
    base_url, seen = start_server(lambda h: send_json(h, 200, completion()))
    adapters(base_url, key=None).generate(REQUEST)
    assert seen[0]["authorization"] is None


def test_the_same_adapter_can_make_several_calls(start_server, adapters):
    base_url, seen = start_server(lambda h: send_json(h, 200, completion("again")))
    adapter = adapters(base_url)
    assert [adapter.generate(REQUEST).text for _ in range(3)] == ["again"] * 3
    assert len(seen) == 3


def test_tool_call_response_over_real_http(start_server, adapters):
    reply = completion(None, [tool_call("read_file", '{"path": "x.py"}')], finish="tool_calls")
    base_url, _ = start_server(lambda h: send_json(h, 200, reply))
    (call,) = adapters(base_url).generate(REQUEST).tool_calls
    assert call.name == "read_file" and call.arguments == {"path": "x.py"}


def test_a_slow_server_gives_a_timeout_quickly(start_server, adapters):
    def slow(handler):
        time.sleep(3)
        send_json(handler, 200, completion())

    base_url, _ = start_server(slow)
    started = time.monotonic()
    with pytest.raises(AdapterError) as info:
        adapters(base_url, timeout=0.5).generate(REQUEST)
    assert info.value.code == TIMEOUT_MODEL
    assert time.monotonic() - started < 2.5


def test_a_closed_port_gives_a_network_error(adapters):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # the socket is closed now, so nothing is listening on that port
    with pytest.raises(AdapterError) as info:
        adapters(f"http://127.0.0.1:{port}/v1").generate(REQUEST)
    assert info.value.code == NETWORK_ERROR_MODEL
    assert KEY not in info.value.message


def test_a_429_with_retry_after_over_the_wire(start_server, adapters):
    base_url, seen = start_server(
        lambda h: send_json(h, 429, {"error": {"message": "Rate limit reached"}}, {"Retry-After": "4"})
    )
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert (info.value.code, info.value.retry_after_s, info.value.status_code) == (RATE_LIMITED_MODEL, 4.0, 429)
    assert len(seen) == 1  # no retry


def test_a_connection_dropped_mid_response_is_an_adapter_error(start_server, adapters):
    def drop(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", "5000")
        handler.end_headers()
        handler.wfile.write(b'{"choices": [{"mess')
        handler.wfile.flush()
        handler.close_connection = True

    base_url, _ = start_server(drop)
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code in (NETWORK_ERROR_MODEL, BAD_RESPONSE)


def test_a_large_response_is_parsed(start_server, adapters):
    text = "x" * 3_000_000
    base_url, _ = start_server(lambda h: send_json(h, 200, completion(text)))
    assert adapters(base_url).generate(REQUEST).text == text


def test_redirects_are_not_followed_and_the_key_goes_nowhere_else(start_server, adapters):
    def redirect(handler):
        handler.send_response(302)
        handler.send_header("Location", "/elsewhere")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    base_url, seen = start_server(redirect)
    with pytest.raises(AdapterError) as info:
        adapters(base_url).generate(REQUEST)
    assert info.value.code == BAD_RESPONSE
    assert [s["path"] for s in seen] == ["/v1/chat/completions"]  # the redirect target was never requested


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


def test_unicode_survives_the_wire_in_both_directions(start_server, adapters):
    text = "café ✓ \U0001f41b"
    base_url, seen = start_server(lambda h: send_json(h, 200, completion(text)))
    request = GenerationRequest(messages=(Message.user(text),))
    assert adapters(base_url).generate(request).text == text
    assert seen[0]["body"]["messages"][0]["content"] == text


def test_close_only_closes_a_client_the_adapter_created():
    shared = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=completion())))
    OpenAICompatibleAdapter(model(), KEY, client=shared).close()
    assert not shared.is_closed  # the caller's client is left alone
    OpenAICompatibleAdapter(model(), KEY).close()  # an adapter-owned client is closed without error
