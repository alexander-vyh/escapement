"""Guard: the manifest must not assert that a host LACKS a documented capability.

escapement-gyp1. Four `unsupported_reason` strings stated as fact that Codex had
no Stop event and no subagent-dispatch event. All were false — Codex documents
11 hook events, publishes a `stop.command` schema, and a payload captured on
2026-09-07 (codex-cli 0.153.4) shows Stop firing and honouring the same
block-decision contract Claude uses.

The cost of that error is not the wording. A manifest string is durable and gets
read as ground truth: an agent repeated the claim to the user on 2026-08-28 as
the reason the Codex plugin omitted a module, and this repo had already paid for
the identical mistake once in PR #111 -> #112. The string re-teaches itself.

So the rule this encodes is narrow and checkable: a reason may say a port has
not been DONE; it may not say the host CANNOT. Porting status is a fact about
this repo, which the manifest owns. Capability is a fact about upstream, which it
does not.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "agent-surfaces" / "manifest.json"

# Events Codex documents (learn.chatgpt.com/docs/hooks) and/or publishes a
# schema for. Claiming any of these does not exist is a factual error.
DOCUMENTED_CODEX_EVENTS = [
    "Stop", "SessionStart", "SessionEnd", "PreToolUse", "PostToolUse",
    "PermissionRequest", "PreCompact", "PostCompact", "UserPromptSubmit",
    "SubagentStart", "SubagentStop",
]

# "Codex has no Stop lifecycle event", "Codex has no equivalent Agent dispatch
# event", "Codex lacks a Stop-time hook" — the claim shape, not one wording.
CAPABILITY_DENIAL = re.compile(
    r"\b(codex)\b[^.]{0,80}?\b(has no|lacks|does not have|doesn'?t have|cannot|can'?t)\b",
    re.I,
)


def _reasons():
    data = json.loads(MANIFEST.read_text())
    found = []

    def walk(node, path="hooks"):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "unsupported_reason" and isinstance(value, str):
                    found.append((path, value))
                else:
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(data)
    return found


def test_no_reason_denies_a_documented_codex_capability():
    offenders = []
    for path, reason in _reasons():
        match = CAPABILITY_DENIAL.search(reason)
        if not match:
            continue
        # A denial is only an error when it denies something upstream documents.
        if any(event.lower() in reason.lower() for event in DOCUMENTED_CODEX_EVENTS):
            offenders.append((path, reason[:150]))
    assert not offenders, (
        "manifest asserts Codex lacks a capability upstream documents; state "
        "porting status instead ('not ported', 'Claude-payload-shaped'), never "
        f"capability: {offenders}"
    )


def test_the_guard_would_catch_the_original_wording():
    """Negative control — the exact strings this bead was filed about."""
    originals = [
        "Fires on the Claude-only Stop event and reads the Claude transcript "
        "path; Codex has no Stop lifecycle event.",
        "Depends on the Claude Stop event; Codex has no Stop-time hook to run "
        "the whole-diff oracle-strength differ.",
        "Fires on Claude Agent-tool dispatch metadata (PreToolUse:Agent); Codex "
        "has no equivalent Agent dispatch event.",
    ]
    for text in originals:
        assert CAPABILITY_DENIAL.search(text), f"guard missed: {text[:60]}"
        assert any(e.lower() in text.lower() for e in DOCUMENTED_CODEX_EVENTS)


def test_porting_status_wording_is_allowed():
    """Positive control — the guard must not forbid honest porting statements."""
    allowed = [
        "Claude-payload-shaped (transcript layout, ScheduleWakeup, task-mode "
        "rungs). Codex HAS a GA Stop event; served by codex_stop_hook.py.",
        "This differ has simply not been ported to Codex. Tracked as escapement-vjv2.",
        "Requires the Claude Agent tool; no Codex port yet.",
    ]
    for text in allowed:
        flagged = CAPABILITY_DENIAL.search(text) and any(
            e.lower() in text.lower() for e in DOCUMENTED_CODEX_EVENTS
        )
        assert not flagged, f"guard wrongly rejects honest wording: {text[:60]}"
