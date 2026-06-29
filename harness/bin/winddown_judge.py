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
    reversible-work-remaining, which prevents nagging a legitimate stop). The judge/rung
    path has no regex floor — None verdict means no classifier fired → allow. The Stop
    hook may still run its separate high-confidence outage sentinel after logging the
    unavailable judge signal.

The Stop hook reads a fresh cached verdict when present, otherwise computes one
inline with the shared bounded local-judge client. A future background monitor
can still warm the same cache.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Callable, Optional, Tuple

# Import the sibling winddown_gate regardless of caller cwd (mirrors stop_hook).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
for _support_dir in (
    pathlib.Path(__file__).resolve().parents[2] / "hooks",
    pathlib.Path(__file__).resolve().parents[2] / "claude" / "hooks",
    pathlib.Path.home() / ".claude" / "hooks",
):
    if str(_support_dir) not in sys.path:
        sys.path.insert(0, str(_support_dir))
import _local_judge_client as _lj  # noqa: E402
import winddown_gate as wg  # noqa: E402

DEFAULT_BASE_URL = _lj.DEFAULT_BASE_URL
# "default" targets whatever model Rapid-MLX currently has loaded (server.py uses the
# same), so a model swap doesn't break the judge.
DEFAULT_MODEL = _lj.DEFAULT_MODEL
# Bounded by default because the currently wired path runs inline during Stop.
# Raise ESCAPEMENT_LOCAL_JUDGE_TIMEOUT deliberately if a machine's model needs longer.
DEFAULT_TIMEOUT = _lj.DEFAULT_TIMEOUT

# The exact system prompt validated live at 11/11.
_SYSTEM = (
    "You judge whether an AI coding agent's message is a WIND-DOWN / WRAP-UP / "
    "decision-punt offer (offering to stop, wrap for the night, hand off, push-and-wrap, "
    "or asking 'which way: continue or stop?') versus a SUBSTANTIVE work question (asking "
    "which library/approach to use, or reporting progress). Answer with ONLY one word: "
    "winddown | not_winddown | unclear"
)


def model_verdict(
    text: str,
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    post: Optional[Callable[[str, dict, float], str]] = None,
) -> Optional[bool]:
    """Ask the local model: is `text` a wind-down offer?

    Returns True (winddown) / False (not_winddown) / None (unclear, error, down, or
    unparseable). FAIL-OPEN: never raises — a model problem yields None and the caller
    treats it as allow (no classifier fired, judge-only architecture).
"""
    return _lj.boolean_verdict(
        text,
        system_prompt=_SYSTEM,
        positive_labels=("winddown",),
        negative_labels=("not_winddown",),
        base_url=base_url,
        model=model,
        timeout=timeout,
        post=post,
    )


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
      - None  → model unavailable / unclear → fail open in the judge/rung path

    The reversible-work gate in winddown_gate.winddown_decision prevents nagging a
    legitimate stop even when the model flags an offer.
    """
    offer = (model_offer is True)
    return wg.winddown_decision(assistant_text, reversible_work_remains, is_offer=offer)
