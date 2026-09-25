"""Run a hook the way the installed Codex plugin runs it.

A Codex fixture proves three things at once, or it proves nothing about Codex:

  registration  the generated plugins/escapement/hooks/hooks.json registers the
                hook for the event and tool it claims;
  payload       the hook is fed the shape Codex 0.156.1 actually sends --
                fixtures/codex_hook_payloads.json was captured from live
                `codex exec` sessions, not written from the docs;
  point of effect  the output is one Codex acts on. `ask` is excluded: the
                capture shows Codex runs a PreToolUse `ask` as an allow and tells
                the model nothing.

So the command executed here is the one read out of the generated hooks.json,
against the vendored plugin copy, with the plugin root substituted as Codex
does. A hook that is not registered, not vendored, or missing a sibling import
fails here the way it would fail in a real session.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parents[2]
PLUGIN_ROOT = REPO / "plugins" / "escapement"
CAPTURE = json.loads((TESTS_DIR / "fixtures" / "codex_hook_payloads.json").read_text())
DISPATCHER = "codex_pretool_dispatch.py"

# Keys Codex reads from a hook's stdout JSON, per event (Codex hooks docs).
# PreToolUse marks a hook run failed when it sees continue/stopReason/
# suppressOutput, so those are excluded for it.
_TOP_LEVEL = {
    "PreToolUse": {"systemMessage", "hookSpecificOutput", "decision", "reason"},
    "PostToolUse": {"systemMessage", "hookSpecificOutput", "decision", "reason",
                    "continue", "stopReason"},
    "UserPromptSubmit": {"systemMessage", "hookSpecificOutput", "decision", "reason",
                         "continue", "stopReason"},
}

# Sub-agent markers make some gates stand down; a test run inside an agent
# session must not inherit them.
_AGENT_ENV = ("CLAUDE_AGENT_NAME", "CLAUDE_AGENT_TYPE", "CLAUDE_SUBAGENT",
              "CLAUDE_TEAM_NAME", "CLAUDE_AGENT_ID", "PREPATCH_VERIFY_DIR")


def payload(name: str, **overrides) -> dict:
    """A captured Codex payload with the fields a test needs replaced."""
    captured = copy.deepcopy(CAPTURE["payloads"][name])
    captured.update(overrides)
    return captured


def patch_text(*files: tuple[str, str], body: str = "+x = 1\n") -> str:
    """An apply_patch body: one ``(kind, path)`` header per file."""
    hunk = {"Add": body, "Update": "@@\n" + body, "Delete": ""}
    headers = "".join(f"*** {kind} File: {path}\n{hunk[kind]}" for kind, path in files)
    return f"*** Begin Patch\n{headers}*** End Patch"


def _registered(event: str, tool_name: str | None) -> list[list[str]]:
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = []
    for item in hooks.get(event, []):
        matcher = item.get("matcher", "")
        if tool_name is not None and matcher not in ("", "*") and not re.fullmatch(matcher, tool_name):
            continue
        for hook in item["hooks"]:
            commands.append(shlex.split(hook["command"].replace("${PLUGIN_ROOT}", str(PLUGIN_ROOT))))
    return commands


def registered_command(event: str, hook: str, tool_name: str | None = None) -> list[str]:
    """The argv Codex runs for ``hook`` on ``event``.

    A Bash gate runs inside the shared dispatcher; the returned argv keeps the
    dispatcher and only this gate's ``--gate``/``--gate-timeout`` pair, so the
    verdict is this gate's and not a sibling's.
    """
    relative = f"claude/hooks/{hook}"
    for argv in _registered(event, tool_name):
        if argv[2].endswith(DISPATCHER) and relative in argv:
            index = argv.index(relative)
            return [*argv[:3], "--gate", relative, *argv[index + 1:index + 3]]
        if argv[2].endswith(relative):
            return argv
    raise AssertionError(f"{hook} is not registered for Codex {event} ({tool_name})")


def isolated_env(tmp_path: Path, **extra: str) -> dict:
    """An environment whose gate signal and session memory stay in tmp_path."""
    env = {key: value for key, value in os.environ.items() if key not in _AGENT_ENV}
    signal = tmp_path / "signal"
    (signal / ".beads").mkdir(parents=True, exist_ok=True)
    env.update(
        HARNESS_ROOT=str(tmp_path / "harness"),
        BEADS_DIR=str(signal / ".beads"),
        GATE_SIGNAL_FALLBACK_DIR=str(signal),
        **extra,
    )
    return env


def run(event: str, hook: str, data: dict, env: dict, timeout: int = 120) -> dict | None:
    """Run the registered command with ``data`` on stdin, as Codex does."""
    argv = registered_command(event, hook, data.get("tool_name"))
    proc = subprocess.run(
        argv, input=json.dumps(data), capture_output=True, text=True,
        cwd=data.get("cwd") or None, env=env, timeout=timeout,
    )
    assert proc.returncode == 0, f"Codex discards a hook that exits {proc.returncode}: {proc.stderr}"
    output = json.loads(proc.stdout) if proc.stdout.strip() else None
    if output is not None:
        assert_codex_reads(event, output)
    return output


def assert_codex_reads(event: str, output: dict) -> None:
    """The output is in the shape Codex acts on for ``event``."""
    unknown = set(output) - _TOP_LEVEL[event]
    assert not unknown, f"Codex {event} does not accept {sorted(unknown)}"
    hook = output.get("hookSpecificOutput")
    if hook is None:
        return
    assert hook.get("hookEventName") == event, hook
    assert hook.get("permissionDecision") != "ask", "Codex runs `ask` as an allow"
    context = hook.get("additionalContext")
    assert context is None or isinstance(context, str)


def denial(output: dict | None) -> str:
    """The reason Codex shows the model when it blocks the call, else fail."""
    assert output is not None, "expected Codex to block the call"
    hook = output.get("hookSpecificOutput") or {}
    assert hook.get("permissionDecision") == "deny", output
    return hook.get("permissionDecisionReason", "")


def is_allowed(output: dict | None) -> bool:
    """True when Codex lets the call run."""
    if output is None:
        return True
    hook = output.get("hookSpecificOutput") or {}
    return hook.get("permissionDecision") != "deny" and output.get("decision") != "block"


def context(output: dict | None, event: str) -> str:
    """The text Codex adds to the model's context, else fail."""
    assert output is not None, f"expected {event} context for the model"
    hook = output.get("hookSpecificOutput") or {}
    assert hook.get("hookEventName") == event
    text = hook.get("additionalContext")
    assert isinstance(text, str) and text, output
    return text
