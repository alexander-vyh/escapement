#!/usr/bin/env python3
"""
Pi PreToolUse gate on omp's blocking `ask` (escapement-fo4v).

omp's `ask` blocks the whole lead until the user answers, and background-job
completions queue behind it. In omp session 01a1183c the lead asked while 16
agents ran; all finished within ~40 minutes and sat unread for ~5h. "A pending
choice blocks only that action" cannot hold while the question freezes every
lane, so:

- an ask is denied while agents this lead started have not reported back, and
- every ask must state what the lead will do if nobody answers: each question
  names a `recommended` option (the one omp's own `ask.timeout` auto-selects)
  and says "If unanswered, I will ...".

The lane signal is the session itself, as the Pi extension writes it: `task`
results announce "(job `X`)", a steered parked agent says "Queued for X (was
parked; revived)", and a delivery carries `<task-result id="X"` (an
`async-result` notice or a `wait` result). A job announced or revived and not
delivered since is still running.

Escape: `--ask-gate-waiver "<reason>"` in a question's text, reason >= 20
characters and not a placeholder; recorded to .beads/.gate-signal.jsonl.

Not detected: a question caused only by the lead's own new code (redirect to
"remove the new dependency") -- nothing cheap and reliable tells that apart.

Fail-open: an unreadable payload or transcript allows the ask and records why.
stdout carries at most the single decision JSON.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

BIN = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))

try:
    from gate_signal_bridge import record_gate_signal
except ImportError:  # pragma: no cover - exercised via a broken install
    def record_gate_signal(*_args, **_kwargs) -> None:
        return None

GATE = "pi_ask_gate"
SPAWNED = re.compile(r"\(job `([^`]+)`\)")
REVIVED = re.compile(r"Queued for (\S+) \(was parked; revived\)")
DELIVERED = re.compile(r"<task-result id=\"([^\"]+)\"|Background job (\S+) has completed")
WAIVER = re.compile(r"--ask-gate-waiver\s+\"([^\"]*)\"")
STATED_DEFAULT = re.compile(r"\bif (?:unanswered|no answer)\b", re.IGNORECASE)
PLACEHOLDERS = {"", "none", "tbd", "todo", "wip", "n/a", "na", "fixme", "?", "??", "???"}


def _texts(row: dict) -> list[str]:
    """Tool-result and system-notice text of one Claude-shaped transcript row;
    the assistant's own words cannot report a job finished."""
    if row.get("type") == "system":
        content = row.get("content")
        return [content] if isinstance(content, str) else []
    message = row.get("message")
    if row.get("type") != "user" or not isinstance(message, dict):
        return []
    texts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str):
            texts.append(block["content"])
    return texts


def running_jobs(transcript_path: str) -> list[str]:
    running: dict[str, None] = {}
    for line in pathlib.Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for text in _texts(row) if isinstance(row, dict) else []:
            # A delivery and a spawn never share one text, so order within it is moot.
            for match in DELIVERED.finditer(text):
                running.pop(match.group(1) or match.group(2), None)
            if "background" in text:
                running.update(dict.fromkeys(SPAWNED.findall(text)))
            running.update(dict.fromkeys(REVIVED.findall(text)))
    return list(running)


def unstated_defaults(questions: list) -> list[str]:
    missing = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("question is not an object")
        text = question.get("question")
        if not isinstance(text, str):
            raise ValueError("question has no text")
        options = question.get("options")
        recommended = question.get("recommended")
        has_option = not options or (
            isinstance(recommended, int) and not isinstance(recommended, bool)
            and 0 <= recommended < len(options)
        )
        if not (has_option and STATED_DEFAULT.search(text)):
            missing.append(str(question.get("id") or text[:60]))
    return missing


def waiver_reason(questions: list) -> str | None:
    for question in questions:
        match = WAIVER.search(question.get("question", ""))
        if match:
            reason = match.group(1).strip()
            if len(reason) >= 20 and reason.lower() not in PLACEHOLDERS:
                return reason
    return None


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> int:
    session_id = ""
    try:
        payload = json.loads(sys.stdin.read())
        session_id = str(payload.get("session_id") or "")
        questions = payload["tool_input"]["questions"]
        if not isinstance(questions, list) or not questions:
            raise ValueError("questions is not a non-empty list")
        missing = unstated_defaults(questions)
        transcript = payload.get("transcript_path")
        running = running_jobs(transcript) if isinstance(transcript, str) and transcript else []
    except Exception as exc:  # noqa: BLE001 -- fail-open with signal
        record_gate_signal("allow", f"fail_open: {str(exc)[:160]}", session_id, gate=GATE)
        return 0

    if missing:
        record_gate_signal("deny", "unstated_default", session_id, ", ".join(missing), gate=GATE)
        deny(
            "Escapement ask gate: `ask` blocks this whole session until someone answers, so every "
            f"question must say what you will do if nobody does. Missing for: {', '.join(missing)}. "
            "Repair: set `recommended` to the conservative option (omp's ask.timeout auto-selects "
            "it) and end the question with \"If unanswered, I will <that option> and continue.\""
        )
        return 0
    if running:
        waiver = waiver_reason(questions)
        if waiver:
            record_gate_signal("waiver-accepted", waiver, session_id, ", ".join(running), gate=GATE)
            return 0
        record_gate_signal("deny", "lanes_running", session_id, ", ".join(running), gate=GATE)
        deny(
            "Escapement ask gate: `ask` blocks this whole session, and agents you started have not "
            f"reported back: {', '.join(running)}. Their results would queue behind the question "
            "until someone answers. Repair: call `wait` (or keep working) and act on each result "
            "first; ask once they have reported. Or ask without blocking: state the question and "
            "your default in your reply and keep going. If the question truly blocks those lanes "
            "too, add --ask-gate-waiver \"<why it cannot wait, >=20 chars>\" to the question text."
        )
        return 0
    record_gate_signal("allow", "no_running_lanes", session_id, gate=GATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
