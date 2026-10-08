"""Which mutation challengers / outcome verifiers a session dispatched.

escapement-obwo: a behaviour change should not land without a challenger, the
role that invents plausible bad implementations which each must fail a test
(claude/rules/agent-teams-default.md, docs/VOCABULARY.md), or the outcome
verifier that checks the actual outcome afterwards.

No agent type carries either role, so the role is read from the WHOLE TOKENS
of the dispatch's identity: its name and subagent_type (Codex: task_name /
agent_type). Never from a description or prompt: "Review the challenger's
tests" describes a reviewer. A review token in the type or the name means a
reviewer, which never counts ("challenger-reviewer", "review_challenger_output"),
and a negating token ("no-challenger-needed") disqualifies the name.

Dispatches are recorded on PreToolUse (Claude `Agent`, Codex spawn_agent, Pi's
translated `Agent`; `_agent_dispatch` owns those shapes). On Claude, the
PostToolUse of a synchronous dispatch carries the reply
(tool_response.content[].text). Whether that reply names bad implementations
is recorded for labelling only. It is a crude reading and never part of the
verdict. tool_response also echoes the prompt, so only the reply fields are read.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_NEGATIONS = frozenset({"no", "not", "non", "without", "skip", "skipped", "never"})
# A dispatch whose type OR name says review is a reviewer, whatever else it says:
# "review-challenger-tests" reviews the challenger, it is not one.
_REVIEW_TOKENS = frozenset({"review", "reviews", "reviewer", "reviewers", "reviewing", "reviewed"})
_BAD_IMPLEMENTATIONS_RE = re.compile(
    r"\b(?:bad|wrong|cheap|plausible|fragile|invalid)\b[\w\s,-]{0,30}\bimplementations?\b"
    r"|\bmutants?\b", re.IGNORECASE)
_IDENTITY_FIELDS = ("subagent_type", "name")
MAX_ENTRIES = 50


def _state_file(session_id: str) -> Path:
    from _shadow_run import add_harness_bin_to_path

    add_harness_bin_to_path()
    from thread_identity import sanitize_session_id
    from would_block_stop import harness_home

    return harness_home() / "shadow-verifier" / f"{sanitize_session_id(session_id) or 'default'}.json"


def _tokens(value: object) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(str(value or "").lower()) if token]


def _role(dispatch: dict) -> str | None:
    if any(_REVIEW_TOKENS & set(_tokens(dispatch.get(field))) for field in _IDENTITY_FIELDS):
        return None
    for field in _IDENTITY_FIELDS:
        tokens = _tokens(dispatch.get(field))
        if _NEGATIONS & set(tokens):
            continue
        if "challenger" in tokens:
            return "mutation-challenger"
        if any(a == "outcome" and b == "verifier" for a, b in zip(tokens, tokens[1:])):
            return "outcome-verifier"
    return None


def _read(path: Path) -> list[dict]:
    try:
        entries = json.loads(path.read_text()).get("challengers", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"challengers": entries[-MAX_ENTRIES:]}))
    temporary.replace(path)


def observe(data: dict, dispatch: dict, session_id: str) -> None:
    """Record a challenger dispatch, or what its synchronous reply said.
    Parallel dispatches are serialized on a lock so none is lost."""
    role = _role(dispatch)
    if role is None:
        return
    path = _state_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _observe_locked(data, dispatch, role, path)


def _observe_locked(data: dict, dispatch: dict, role: str, path: Path) -> None:
    entries = _read(path)
    tool_use_id = data.get("tool_use_id")
    if data.get("hook_event_name") == "PostToolUse":
        response = data.get("tool_response")
        content = response.get("content") if isinstance(response, dict) else None
        reply = "\n".join(block.get("text", "") for block in content or []
                          if isinstance(block, dict) and isinstance(block.get("text"), str))
        for entry in entries:
            if tool_use_id and entry.get("tool_use_id") == tool_use_id:
                entry["names_bad_implementations"] = bool(_BAD_IMPLEMENTATIONS_RE.search(reply))
        _write(path, entries)
        return
    entries.append({"name": dispatch.get("name") or "unknown", "role": role,
                    "subagent_type": dispatch.get("subagent_type") or None,
                    "tool_use_id": tool_use_id, "names_bad_implementations": None})
    _write(path, entries)


def dispatched(session_id: str) -> list[dict]:
    return _read(_state_file(session_id))
