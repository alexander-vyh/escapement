"""Oracle for SessionStart rules injection: the rule text itself, in parts.

Business outcome
----------------
Every always-on rule's text (each rule file minus its marked reference
sections, which stay on disk behind a pointer) reaches the agent at session
start on Claude, Codex and Pi.

Host limits, measured (escapement-s8qr, 2026-10-07, see PR #269):
- Claude Code 2.1.293: a single hook's additionalContext over 10,000 chars is
  saved to a file and the model sees a 2 KB preview. The limit is per hook:
  six hooks of 9,000 chars each (54,000 total) all arrived byte-identical.
  Parallel hooks arrive in completion order, not registration order.
- Codex 0.160.1: a hook output over ~10,000 BYTES (2,500 tokens at bytes/4) is
  head+tail truncated with the middle elided. Also per hook: six 9,000-byte
  outputs arrived intact. An 8,000-char output of 12,320 bytes was truncated,
  so the budget is UTF-8 bytes, not characters.
- Pi: no cap below the dispatcher's 1 MB; it runs the hook without arguments.

So the injector emits ordered parts, each a self-describing single-line header
plus whole rules, each part at most PART_LIMIT_BYTES.

Independent source of truth
---------------------------
The rule files each host package ships. The oracle is the source itself: the
parts' bodies, concatenated, must equal the shipped rules' heads byte for
byte, in order. No phrase list, no hand-written summary: deleting or rewording
any sentence of a rule's head makes the old output fail (proved below).

The heads are derived here from the files with this module's own reader, and
the parts come from executing each packaged hook exactly as its host's
registration invokes it.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PART_LIMIT_BYTES = 9_000
DETAIL_START = "<!-- escapement:detail:start -->"
DETAIL_END = "<!-- escapement:detail:end -->"

PACKAGES = {
    "claude": {
        "hook": ROOT / "plugins/escapement-claude/hooks/inject_rules.py",
        "registration": ROOT / "plugins/escapement-claude/hooks/hooks.json",
        "events": ("SessionStart",),
    },
    "codex": {
        "hook": ROOT / "plugins/escapement/claude/hooks/inject_rules.py",
        "registration": ROOT / "plugins/escapement/hooks/hooks.json",
        "events": ("SessionStart",),
    },
    # Pi's dispatcher runs a session gate with no arguments (gates.json).
    "pi": {
        "hook": ROOT / "plugins/escapement-pi/claude/hooks/inject_rules.py",
        "registration": None,
        "events": ("SessionStart",),
    },
}


# --- The source: each shipped rule's head ----------------------------------

def head_of(text: str) -> str:
    """A rule file minus each closed detail region and its HTML comments."""
    while True:
        start = text.find(DETAIL_START)
        end = text.find(DETAIL_END, start + 1) if start >= 0 else -1
        if start < 0 or end < 0:
            break
        text = text[:start] + text[end + len(DETAIL_END):]
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def heads(rules_dir: Path) -> list[tuple[str, str]]:
    out = [(p.name, head_of(p.read_text(encoding="utf-8"))) for p in sorted(rules_dir.glob("*.md"))]
    assert out, f"{rules_dir} ships no rules"
    return out


def has_detail(rules_dir: Path, name: str) -> bool:
    text = (rules_dir / name).read_text(encoding="utf-8")
    return head_of(text) != re.sub(r"<!--.*?-->", "", text, flags=re.S)


# --- The output: each packaged hook, run as its host runs it ---------------

def registered_args(registration: Path, event: str) -> list[list[str]]:
    """The arguments each registered inject_rules command passes, in order."""
    groups = json.loads(registration.read_text(encoding="utf-8"))["hooks"].get(event, [])
    out = []
    for group in groups:
        for hook in group["hooks"]:
            argv = shlex.split(hook["command"])
            scripts = [i for i, a in enumerate(argv) if a.endswith("/inject_rules.py")]
            if scripts:
                out.append(argv[scripts[0] + 1:])
    return out


def run_hook(hook: Path, args: list[str], event: str = "SessionStart") -> dict | None:
    completed = subprocess.run(
        [sys.executable, "-B", str(hook), *args],
        input=json.dumps({"hook_event_name": event, "session_id": "s"}),
        capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    if not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)["hookSpecificOutput"]


def contexts_for(host: str, event: str) -> tuple[list[str], int]:
    """(non-empty additionalContext per registered part, registered part count)."""
    package = PACKAGES[host]
    arg_lists = (
        registered_args(package["registration"], event) if package["registration"] else [[]]
    )
    assert arg_lists, f"{host}: inject_rules is not registered for {event}"
    out = []
    for args in arg_lists:
        result = run_hook(package["hook"], args, event)
        if result is not None:
            assert result["hookEventName"] == event
            out.append(result["additionalContext"])
    return out, len(arg_lists)


# --- The oracle ------------------------------------------------------------

def split_part(context: str) -> tuple[str, str]:
    header, sep, body = context.partition("\n\n")
    assert sep and "\n" not in header, "a part must open with a single header line"
    return header, body


def assert_reproduces(contexts: list[str], rules_dir: Path) -> None:
    """The parts' bodies, in order, are exactly the shipped heads, in order,
    and every part holds whole rules only."""
    expected = heads(rules_dir)
    bodies = [split_part(c)[1] for c in contexts]
    assert "".join(bodies) == "".join(text for _, text in expected), (
        "concatenated parts differ from the shipped rule files"
    )
    cursor = 0
    for body in bodies:
        taken = ""
        while len(taken) < len(body):
            taken += expected[cursor][1]
            cursor += 1
        assert taken == body, "a part splits a rule; parts must hold whole rules"


@pytest.fixture(scope="module", params=[
    (host, event) for host, p in PACKAGES.items() for event in p["events"]
], ids=lambda he: f"{he[0]}-{he[1]}")
def shipped(request):
    host, event = request.param
    contexts, registered = contexts_for(host, event)
    return host, contexts, registered, PACKAGES[host]["hook"].parent.parent / "rules"


def test_parts_reproduce_the_shipped_rules_byte_for_byte(shipped):
    _, contexts, _, rules_dir = shipped
    assert_reproduces(contexts, rules_dir)


def test_every_part_fits_the_measured_host_limit(shipped):
    host, contexts, _, _ = shipped
    # Pi has no inline cap; its dispatcher reads at most 1 MB of hook output.
    limit = 1_048_576 if PACKAGES[host]["registration"] is None else PART_LIMIT_BYTES
    for k, context in enumerate(contexts, 1):
        size = len(context.encode("utf-8"))
        assert size <= limit, f"{host} part {k} is {size} bytes"


def test_registration_carries_every_part_with_headroom(shipped):
    host, contexts, registered, _ = shipped
    if PACKAGES[host]["registration"] is None:
        assert len(contexts) == 1, "Pi runs the hook once, unsplit"
        return
    assert len(contexts) < registered, (
        f"{host}: {len(contexts)} parts fill all {registered} registered entries; "
        "register more before the rules outgrow them"
    )
    assert not any("WARNING" in c for c in contexts)


def test_every_part_is_self_describing_and_authoritative(shipped):
    """Parts arrive in completion order, so each carries its own label,
    the override framing, and pointers for what it holds back."""
    host, contexts, _, rules_dir = shipped
    total = len(contexts) if PACKAGES[host]["registration"] is None else None
    expected = iter(heads(rules_dir))
    for k, context in enumerate(contexts, 1):
        header, body = split_part(context)
        assert f"part {k} of " in header
        if total is not None:
            assert f"part {k} of {total}" in header
        assert "OVERRIDE default behavior" in header and "MUST follow" in header
        carried = ""
        while len(carried) < len(body):
            name, text = next(expected)
            carried += text
            assert name in header, f"{host} part {k} does not name {name}"
            if has_detail(rules_dir, name):
                assert f"{rules_dir.resolve()}/" in header, (
                    f"{name}: held-back reference with no path to read it"
                )


# --- The oracle catches drift (it is the source, not a phrase list) --------
# The "old output" is the shipped Claude package's real output, produced once;
# each test then edits a copy of its rules and checks the oracle notices.

CLAUDE_RULES = PACKAGES["claude"]["hook"].parent.parent / "rules"


@pytest.fixture(scope="module")
def old_output() -> list[str]:
    return contexts_for("claude", "SessionStart")[0]


def _rules_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(CLAUDE_RULES, tmp_path / "rules"))


def test_positive_control_old_output_matches_unchanged_rules(tmp_path, old_output):
    assert_reproduces(old_output, _rules_copy(tmp_path))


@pytest.mark.parametrize("rule", sorted(p.name for p in CLAUDE_RULES.glob("*.md")))
def test_deleting_any_sentence_of_a_rule_fails_the_old_output(tmp_path, old_output, rule):
    rules_dir = _rules_copy(tmp_path)
    path = rules_dir / rule
    text = path.read_text(encoding="utf-8")
    sentence = max(
        (line for line in head_of(text).splitlines() if "<!--" not in line), key=len
    )
    path.write_text(text.replace(sentence, "", 1), encoding="utf-8")

    with pytest.raises(AssertionError):
        assert_reproduces(old_output, rules_dir)


def test_rewording_a_prohibition_fails_the_old_output(tmp_path, old_output):
    """The failure that sank the bindings: a prohibition softened in place."""
    rules_dir = _rules_copy(tmp_path)
    path = rules_dir / "continuation-harness.md"
    text = path.read_text(encoding="utf-8")
    weakened = text.replace("carve-out does NOT cover", "carve-out covers, when you feel like it,", 1)
    assert weakened != text
    path.write_text(weakened, encoding="utf-8")

    with pytest.raises(AssertionError):
        assert_reproduces(old_output, rules_dir)


def test_the_hook_follows_an_edited_source(tmp_path):
    """The other half: after a rule changes, the hook's new output reproduces it."""
    src = PACKAGES["claude"]["hook"]
    hook = tmp_path / "plugin/hooks" / src.name
    hook.parent.mkdir(parents=True)
    shutil.copy2(src, hook)
    rules_dir = Path(shutil.copytree(CLAUDE_RULES, tmp_path / "plugin/rules"))
    path = rules_dir / "continuation-harness.md"
    path.write_text(path.read_text(encoding="utf-8").replace("NOT", "not", 1), encoding="utf-8")
    contexts = []
    for args in registered_args(PACKAGES["claude"]["registration"], "SessionStart"):
        result = run_hook(hook, args)
        if result:
            contexts.append(result["additionalContext"])

    assert_reproduces(contexts, rules_dir)


def test_a_summary_in_place_of_a_rule_fails(tmp_path, old_output):
    """Negative control for the invalid class 'compact binding instead of text'."""
    rules_dir = _rules_copy(tmp_path)
    name, text = heads(rules_dir)[0]
    summarised = [p.replace(text, f"# {name}\n\nFollow this rule.\n", 1) for p in old_output]
    assert summarised != old_output

    with pytest.raises(AssertionError):
        assert_reproduces(summarised, rules_dir)


# --- Requirements a review found missing stay injected ----------------------
# Each was once held back behind a detail marker (or summarised away). Moving a
# marker back over one must fail here, on every host that ships the rule.

PINNED_REQUIREMENTS = [
    ("continuation-harness.md", 'carve-out does NOT cover a merge that triggers'),
    ("continuation-harness.md", 'Do **not** pick up unrelated ready tasks from `bd ready` to drain the queue'),
    ("continuation-harness.md", 'Config/docs work being TDD-exempt does NOT exempt it from a continuation-harness contract.'),
    ("continuation-harness.md", '`permissionDecisionReason` — verbatim in substance'),
    ("continuation-harness.md", 'If you edited a tracked,'),
    ("continuation-harness.md", 'do NOT register a passing parse-check as the contract'),
    ("continuation-harness.md", 'Don\'t write "I\'ll check back" as prose and end the turn'),
    ("tdd-enforcement.md", '(d) a human ack'),
    ("tdd-enforcement.md", '## Behavioral config is not exempt'),
    ("tdd-enforcement.md", 'write the failing test FIRST, run it and confirm it fails *for the right reason*'),
    ("tdd-enforcement.md", 'strategy has been reviewed for oracle quality'),
    ("molecule-awareness.md", '**Scope changes are always human-driven.**'),
    ("molecule-awareness.md", 'Do not ask the user to confirm the instruction they'),
    ("outcome-ownership.md", 'has independently verified green status, you are durably authorized to follow the'),
    ("outcome-ownership.md", 'Never make stopping one of the'),
    ("outcome-ownership.md", '### Wind-Down Anti-Patterns (The Silent Killer)'),
    ("outcome-ownership.md", '→ There is no follow-up. You are the follow-up. Do the remaining items NOW.'),
    ("agent-teams-default.md", '**Always pair** for feature/epic work with behavioral specs'),
    ("agent-teams-default.md", 'success criteria and NEVER from the code'),
    ("agent-teams-default.md", 'including the tempting shortcut, and BLOCKS implementation until the named'),
    ("agent-teams-default.md", 'NEVER accepting "tests pass"'),
    ("agent-teams-default.md", 'do not dispatch execution for them'),
    ("outcome-ownership.md", '**An answered question is done.** Once you hold an answer the user can act on, deliver it'),
    ("research-findings-persistence.md", 'If a file is missing or a stub, **persist the payload the agent returned**; re-dispatch'),
    ("research-findings-persistence.md", 'persists that payload verbatim at once. Persistence is bookkeeping: never a reason to'),
    ("research-findings-persistence.md", 'An unavailable optional comparison is **unknown**, not authority to'),
    ("research-findings-persistence.md", 'uncertainty tags live **inline in the file**, never only in the message.'),
    ("research-findings-persistence.md", '**prints the path and offers cleanup** — no'),
    ("research-findings-persistence.md", 'The count check is the headline guard, so it **must** carry its own `|| exit 1`'),
]


def missing_pins(contexts: list[str], rules_dir: Path) -> list[str]:
    injected = "\n".join(contexts)
    return [
        f"{rule}: {fragment}" for rule, fragment in PINNED_REQUIREMENTS
        if (rules_dir / rule).exists() and fragment not in injected
    ]


def test_pinned_requirements_reach_the_session(shipped):
    host, contexts, _, rules_dir = shipped
    assert missing_pins(contexts, rules_dir) == [], host


# Directives that pushed Codex/Pi agents to dispatch by default (Cake 129-tree
# scan: "policy suggests always using parallel processing"). Removed on purpose;
# re-adding one must fail here on every host.
REMOVED_DIRECTIVES = [
    "dispatch agents. This includes research",
    "Everything else should go to agents",
    "instead of dispatching a team",
    "instead of dispatching explore agents",
    "dispatch for it now",
]
INLINE_DEFAULT = "**Work inline by default.** Dispatch an agent only when"


def test_dispatch_by_default_never_reaches_the_session(shipped):
    host, contexts, _, _ = shipped
    injected = "\n".join(contexts)
    assert [d for d in REMOVED_DIRECTIVES if d in injected] == [], host
    assert INLINE_DEFAULT in injected, host


def test_pins_cover_files_each_host_ships():
    for rule, _ in PINNED_REQUIREMENTS:
        assert (CLAUDE_RULES / rule).exists(), f"pinned rule {rule} is not shipped"


def test_a_marker_moved_back_over_a_pinned_requirement_fails(tmp_path):
    """Negative control: hide the bd-ready prohibition in a detail region again."""
    src = PACKAGES["claude"]["hook"]
    hook = tmp_path / "plugin/hooks" / src.name
    hook.parent.mkdir(parents=True)
    shutil.copy2(src, hook)
    rules_dir = Path(shutil.copytree(CLAUDE_RULES, tmp_path / "plugin/rules"))
    path = rules_dir / "continuation-harness.md"
    text = path.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("Do **not** pick up unrelated ready tasks"))
    path.write_text(
        text.replace(line, f"{DETAIL_START}\n{line}\n{DETAIL_END}", 1), encoding="utf-8"
    )
    contexts = []
    for args in registered_args(PACKAGES["claude"]["registration"], "SessionStart"):
        result = run_hook(hook, args)
        if result:
            contexts.append(result["additionalContext"])

    assert any("bd ready" in m for m in missing_pins(contexts, rules_dir))


# --- Registration: only where the host can inject, only when it should ----

def _inject_groups(registration: Path) -> dict[str, list[dict]]:
    hooks = json.loads(registration.read_text(encoding="utf-8"))["hooks"]
    return {
        event: [g for g in groups if any("inject_rules.py" in h["command"] for h in g["hooks"])]
        for event, groups in hooks.items()
    }


def test_codex_injects_at_startup_clear_and_compact_but_not_resume_or_precompact():
    """Codex 0.160.1's PreCompact output cannot carry additionalContext, and its
    SessionStart matcher filters on source (measured: '' also fires on resume,
    which would stack the rules onto history again)."""
    groups = _inject_groups(PACKAGES["codex"]["registration"])
    assert groups.get("PreCompact", []) == []
    assert groups["SessionStart"]
    assert {g["matcher"] for g in groups["SessionStart"]} == {"startup|clear|compact"}


def test_claude_injects_at_startup_clear_and_compact():
    groups = _inject_groups(PACKAGES["claude"]["registration"])
    assert {g["matcher"] for g in groups["SessionStart"]} == {"startup|clear|compact"}
