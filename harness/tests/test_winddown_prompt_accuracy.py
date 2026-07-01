"""LIVE prompt-accuracy oracle for the wind-down judge's _SYSTEM classifier.

WHY THIS EXISTS (the gap it closes)
-----------------------------------
test_winddown_judge.py and test_winddown_gate.py inject the transport (`post=`) and
mock the verdict, so they test the ROUTING (verdict -> block/allow) but NEVER the
PROMPT. A prompt can pass every mocked test and still misclassify real messages — which
is exactly what happened: the narrow wrap-only prompt classified a real permission-
solicitation ("Want me to dig up X and draft Y? I can do both now — you'd just review")
as not_winddown, so the Stop gate allowed it and the user got a do-nothing solicitation
after 90s of churn. No mocked test could catch that because none of them exercise the
model. This test does.

THE ORACLE
----------
Business invariant: a turn-final message that offers to do obvious in-scope, reversible
work and asks permission instead of doing it MUST classify as wind-down (so the gate
blocks and the agent proceeds); a message that reports progress or asks a GENUINE
decision the user must own MUST NOT (so the gate does not nag a legitimate turn).

Independent source of truth: the labeled fixture set (fixtures/winddown_labeled.json),
authored from the real failure plus adversarial negative controls, NOT from the prompt's
wording. `expect` is the GATE DECISION (block/allow) the user experiences — not the raw
3-way label — because for a non-punt both not_winddown AND unclear->None both mean allow.

Fragile implementation this rejects: the pre-fix wrap-only prompt. It classifies the
permission-punt fixtures (P1/P4/P5) as not_winddown -> allow, so this test FAILS against
it. It also rejects an over-broad prompt that flags genuine decisions (N1/N4) as
wind-down — those are the negative controls.

TRANSPORT vs CLASSIFICATION: the local model server intermittently returns an empty
completion (message with no `content`) -> the client fails open to None. None is a
TRANSPORT outcome, not a classification, so we retry (spaced) to obtain real verdicts and
assert only on what the model actually returned. A positive case that never yields a real
verdict is an infra outage (skip that case), not a prompt regression. A single real
not_winddown on a positive — or a single real winddown on a negative — is a hard failure.

This test is SKIPPED when the local judge is unreachable (it cannot run without the
model). That is legitimate environment-gating, not oracle suppression: when the model IS
up, every fixture is asserted.
"""
import json
import os
import pathlib
import sys
import time

import pytest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
HOOKS = pathlib.Path(__file__).resolve().parents[2] / "claude" / "hooks"
for p in (str(BIN), str(HOOKS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import winddown_judge as wj  # noqa: E402
import _local_judge_client as lj  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "winddown_labeled.json"
CASES = json.loads(FIXTURE.read_text())

# Spaced retries absorb the server's intermittent empty-content responses (a transport
# fail-open, tracked separately), without masking a real misclassification. A bounded
# per-call timeout keeps a pathological hang from eating the default 60s per attempt;
# on a healthy server each classification is ~3s.
_MAX_ATTEMPTS = 3
_SPACING_S = 1.0
os.environ.setdefault("ESCAPEMENT_LOCAL_JUDGE_TIMEOUT", "20")


def _judge_up() -> bool:
    """Fast reachability probe: GET /v1/models with a short timeout.

    Deliberately NOT a generation round-trip — the server intermittently returns an
    empty completion (the transport fail-open tracked separately), so gating collection
    on a clean generation would spuriously skip the whole module. `/v1/models` answers
    in ~0.3s when the server is up and is a true is-it-listening check.
    """
    import urllib.request
    url = lj.configured_base_url().rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _real_verdicts(text, want_at_least=2):
    """Sample model_verdict, spaced, keeping only NON-None (real) verdicts.

    Stops early once `want_at_least` real verdicts are collected. Returns the list of
    booleans the model actually produced (True=winddown, False=not_winddown); an empty
    list means the transport never yielded a verdict (infra outage for this case).
    """
    got = []
    for i in range(_MAX_ATTEMPTS):
        v = wj.model_verdict(text)
        if v is not None:
            got.append(v)
            if len(got) >= want_at_least:
                break
        if i < _MAX_ATTEMPTS - 1:
            time.sleep(_SPACING_S)
    return got


pytestmark = pytest.mark.skipif(not _judge_up(), reason="local judge (localhost:8000) unreachable")


@pytest.mark.parametrize("case", [c for c in CASES if c["expect"] == "block"], ids=lambda c: c["id"])
def test_positive_cases_classify_as_winddown(case):
    """Permission-punt / wrap offers must be flagged winddown (True) whenever answered."""
    verdicts = _real_verdicts(case["text"])
    if not verdicts:
        pytest.skip("%s: judge transport yielded no verdict (server empty-content outage)" % case["id"])
    # Every real verdict must be winddown. A single real not_winddown is the regression
    # (the wrap-only prompt would produce exactly that for the permission-punt cases).
    assert all(v is True for v in verdicts), (
        "%s (%s): expected winddown, got real verdicts %s — prompt does not catch this class"
        % (case["id"], case["class"], ["winddown" if v else "not_winddown" for v in verdicts])
    )
    # And the gate decision the user feels must be block (work remains -> not a legit stop).
    decision, _ = wj.decide(case["text"], reversible_work_remains=True, model_offer=verdicts[-1])
    assert decision == "block"


@pytest.mark.parametrize("case", [c for c in CASES if c["expect"] == "allow"], ids=lambda c: c["id"])
def test_negative_cases_are_not_flagged_winddown(case):
    """Genuine decisions / progress reports must NEVER be misflagged as a punt."""
    verdicts = _real_verdicts(case["text"])
    if not verdicts:
        pytest.skip("%s: judge transport yielded no verdict (server empty-content outage)" % case["id"])
    # No real verdict may be winddown — that would be the over-correction (nagging a
    # legitimate clarifying question). not_winddown (or None->allow) is correct.
    assert all(v is False for v in verdicts), (
        "%s (%s): must NOT be winddown, got real verdicts %s — prompt over-flags genuine decisions"
        % (case["id"], case["class"], ["winddown" if v else "not_winddown" for v in verdicts])
    )
    decision, _ = wj.decide(case["text"], reversible_work_remains=True, model_offer=verdicts[-1])
    assert decision == "allow"
