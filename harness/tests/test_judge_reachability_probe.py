#!/usr/bin/env python3
"""_judge_up() must skip on DEAD transport but never mask a live misclassification.

Guards the two-endpoint reachability probe added for escapement-pgo/lby9. The probe
exists because /v1/models can answer 200 while the chat endpoint is dead (HTTP 000),
which made the prompt-accuracy positives FAIL (all-None verdicts) instead of SKIP.

THE INVARIANT THAT MUST NOT REGRESS (never-suppress):
  A chat endpoint that RESPONDS 2xx — including the intermittent empty-content fail-open
  the retry loop is designed to absorb — counts as UP, so a live-but-MISCLASSIFYING model
  still reaches the assertion and still FAILS. The skip may only cover dead transport.

Fragile implementation this rejects: gating _judge_up() on "did a generation return
content?" — that would skip when the model is up but wrong, suppressing escapement-u4a0's
oracle. These tests assert the probe keys on TRANSPORT STATUS, not completion content.

Run: python3 -m pytest harness/tests/test_judge_reachability_probe.py -q
"""

import importlib.util
import pathlib
import sys
import urllib.error
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent


def _load_module():
    # Load the prompt-accuracy module without triggering its module-level pytestmark
    # skip (that only affects collection of ITS tests, not import).
    spec = importlib.util.spec_from_file_location(
        "tpa_probe", TESTS / "test_winddown_prompt_accuracy.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


tpa = _load_module()


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_router(models_status=200, chat=("ok", 200)):
    """Build a urlopen fake. `chat` is ('ok', status) | ('httperror', code) | ('refused', None)."""
    def fake(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/models"):
            if models_status is None:
                raise urllib.error.URLError("models refused")
            return _Resp(models_status)
        # chat endpoint
        kind, val = chat
        if kind == "ok":
            return _Resp(val)
        if kind == "httperror":
            raise urllib.error.HTTPError(url, val, "err", {}, None)
        raise urllib.error.URLError("chat refused")
    return fake


def test_both_up_returns_true():
    with mock.patch("urllib.request.urlopen", _urlopen_router(200, ("ok", 200))):
        assert tpa._judge_up() is True


def test_chat_200_empty_content_still_up():
    """The empty-content fail-open answers 2xx — transport UP => run (retry loop absorbs
    the empty content). Must NOT skip."""
    with mock.patch("urllib.request.urlopen", _urlopen_router(200, ("ok", 204))):
        assert tpa._judge_up() is True, "a 2xx chat response is reachable — must run, not skip"


def test_chat_connection_refused_skips():
    """models=200 but chat transport dead (the observed 2026-07-07 state) => skip."""
    with mock.patch("urllib.request.urlopen", _urlopen_router(200, ("refused", None))):
        assert tpa._judge_up() is False


def test_chat_5xx_skips():
    """A genuine chat server fault (5xx) is not a verdict => skip, don't fail."""
    with mock.patch("urllib.request.urlopen", _urlopen_router(200, ("httperror", 503))):
        assert tpa._judge_up() is False


def test_models_down_skips():
    with mock.patch("urllib.request.urlopen", _urlopen_router(None, ("ok", 200))):
        assert tpa._judge_up() is False


def test_models_non_200_skips():
    with mock.patch("urllib.request.urlopen", _urlopen_router(503, ("ok", 200))):
        assert tpa._judge_up() is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
