"""Tests for the shared local OpenAI-compatible judge client."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import _local_judge_client as lj  # noqa: E402


class _ChatHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size).decode("utf-8")
        self.__class__.requests.append((self.path, json.loads(body)))
        payload = {"choices": [{"message": {"content": "stop_solicitation"}}]}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002
        return None


def test_boolean_verdict_uses_configured_openai_compatible_contract(monkeypatch):
    monkeypatch.setenv("ESCAPEMENT_LOCAL_JUDGE_BASE_URL", "http://127.0.0.1:8123/custom/v1/")
    monkeypatch.setenv("ESCAPEMENT_LOCAL_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("ESCAPEMENT_LOCAL_JUDGE_TIMEOUT", "2.5")
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return "stop_solicitation"

    verdict = lj.boolean_verdict(
        "I can hand this back here; say the word and I will proceed.",
        system_prompt="label the message",
        positive_labels=("stop_solicitation",),
        negative_labels=("not_stop_solicitation",),
        post=post,
    )

    assert verdict is True
    assert calls == [
        (
            "http://127.0.0.1:8123/custom/v1/chat/completions",
            {
                "model": "judge-model",
                "messages": [
                    {"role": "system", "content": "label the message"},
                    {
                        "role": "user",
                        "content": "I can hand this back here; say the word and I will proceed.",
                    },
                ],
                "max_tokens": 32,
                "enable_thinking": False,
            },
            2.5,
        )
    ]


def test_boolean_verdict_checks_negative_label_before_positive_substring():
    verdict = lj.boolean_verdict(
        "want me to wrap for the night, or keep going?",
        system_prompt="label the message",
        positive_labels=("stop_solicitation",),
        negative_labels=("not_stop_solicitation",),
        post=lambda url, payload, timeout: "not_stop_solicitation",
    )

    assert verdict is False


def test_boolean_verdict_fails_open_on_transport_error():
    def boom(url, payload, timeout):
        raise TimeoutError("model server down")

    assert lj.boolean_verdict(
        "I can stop here.",
        system_prompt="label the message",
        positive_labels=("stop_solicitation",),
        negative_labels=("not_stop_solicitation",),
        post=boom,
    ) is None


def test_boolean_verdict_fails_open_on_unclear_response():
    assert lj.boolean_verdict(
        "I can stop here.",
        system_prompt="label the message",
        positive_labels=("stop_solicitation",),
        negative_labels=("not_stop_solicitation",),
        post=lambda url, payload, timeout: "unclear",
    ) is None


def test_default_post_parses_real_openai_compatible_http_response():
    _ChatHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        verdict = lj.boolean_verdict(
            "I can hand this back here; say the word and I will proceed.",
            system_prompt="label the message",
            positive_labels=("stop_solicitation",),
            negative_labels=("not_stop_solicitation",),
            base_url=base_url,
            model="fake-local-model",
            timeout=2,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert verdict is True
    assert _ChatHandler.requests == [
        (
            "/v1/chat/completions",
            {
                "model": "fake-local-model",
                "messages": [
                    {"role": "system", "content": "label the message"},
                    {
                        "role": "user",
                        "content": "I can hand this back here; say the word and I will proceed.",
                    },
                ],
                "max_tokens": 32,
                "enable_thinking": False,
            },
        )
    ]


def test_health_check_reports_unavailable_without_raising():
    def boom(url, payload, timeout):
        raise ConnectionRefusedError("no listener")

    result = lj.health_check(post=boom)

    assert result["ok"] is False
    assert result["base_url"] == lj.DEFAULT_BASE_URL
    assert result["model"] == lj.DEFAULT_MODEL
    assert result["reason"] == "unavailable"
