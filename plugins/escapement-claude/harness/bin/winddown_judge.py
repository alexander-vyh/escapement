#!/usr/bin/env python3
"""Local-LLM judge layer for the continuation-harness wind-down rung.

Calls the local Rapid-MLX model (OpenAI-compatible API at localhost:8000, the same
backend the `local-llm` MCP server wraps) to classify whether an assistant turn-final
message is a wind-down / decision-punt offer. This is the SWE-PRM pattern — a separate
model judging the trajectory — and it validated 11/11 on the labeled set live, handling
nuance that regex patterns cannot.

Two invariants, both TESTED:
  - FAIL-OPEN: any model error / timeout / unparseable verdict → None, and `decide`
    returns ("allow", "no_winddown_offer"). The gate NEVER depends on the model being up.
    The outage is signalled at the hook layer (stop_hook._winddown_override) per
    gate-design Rule 2.
  - JUDGE OWNS RECALL: `decide` blocks only when the model flags an offer (gated by
    reversible-work-remaining, which prevents nagging a legitimate stop). There is no
    regex floor to fall back to — None verdict means no classifier fired → allow.

The model call belongs in a BACKGROUND monitor (so its latency never blocks the user's
turn); the Stop hook reads the cached verdict and calls `decide`.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Callable, Optional, Tuple

# Import the sibling winddown_gate regardless of caller cwd (mirrors stop_hook).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import winddown_gate as wg  # noqa: E402

DEFAULT_BASE_URL = "http://localhost:8000/v1"
# "default" targets whatever model Rapid-MLX currently has loaded (server.py uses the
# same), so a model swap doesn't break the judge.
DEFAULT_MODEL = "default"
# Generous: the judge runs in a background monitor, not the turn's critical path, and a
# cold model can take >5s (the 01:41 false-negative was a 5s ping against a loading model).
DEFAULT_TIMEOUT = 60

# The exact system prompt validated live at 11/11.
_SYSTEM = (
    "You judge whether an AI coding agent's message is a WIND-DOWN / WRAP-UP / "
    "decision-punt offer (offering to stop, wrap for the night, hand off, push-and-wrap, "
    "or asking 'which way: continue or stop?') versus a SUBSTANTIVE work question (asking "
    "which library/approach to use, or reporting progress). Answer with ONLY one word: "
    "winddown | not_winddown | unclear"
)


def _default_post(payload: dict, *, base_url: str, timeout: int) -> str:
    """POST to the OpenAI-compatible endpoint; return the model's raw reply text."""
    import httpx  # lazy: a missing httpx must not break import (fail-open philosophy)

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def model_verdict(
    text: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    post: Optional[Callable[[dict], str]] = None,
) -> Optional[bool]:
    """Ask the local model: is `text` a wind-down offer?

    Returns True (winddown) / False (not_winddown) / None (unclear, error, down, or
    unparseable). FAIL-OPEN: never raises — a model problem yields None and the caller
    treats it as allow (no classifier fired, judge-only architecture).
"""
    if not text or not isinstance(text, str):
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ],
        "max_tokens": 8,
        "enable_thinking": False,
    }
    try:
        if post is None:
            content = _default_post(payload, base_url=base_url, timeout=timeout)
        else:
            content = post(payload)
    except Exception:
        return None  # fail-open: down / timeout / network / parse → allow (judge-only)
    low = (content or "").strip().lower()
    if "not_winddown" in low or "not winddown" in low:
        return False
    if "winddown" in low:
        return True
    return None


def decide(
    assistant_text: Optional[str],
    reversible_work_remains: bool,
    *,
    model_offer: Optional[bool] = None,
) -> Tuple[str, str]:
    """Route the (pre-computed) model verdict through the wind-down rung.

    The judge is the sole classifier. `model_offer` is the verdict from `model_verdict`:
      - True  → offer detected → rung decides based on reversible_work_remains
      - False → not an offer → allow
      - None  → model unavailable / unclear → fail open to allow ("semantic or nothing")

    The reversible-work gate in winddown_gate.winddown_decision prevents nagging a
    legitimate stop even when the model flags an offer.
    """
    offer = (model_offer is True)
    return wg.winddown_decision(assistant_text, reversible_work_remains, is_offer=offer)
