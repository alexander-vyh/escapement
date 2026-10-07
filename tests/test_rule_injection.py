"""Oracle for SessionStart rules injection.

Business outcome
----------------
Every always-on rule's binding requirement reaches the agent at session start
and after compaction, on Claude, Codex and Pi. Before this, the injector
concatenated every rule (~42 KB). Claude Code inlines a hook's
``additionalContext`` only up to 10,000 characters; past that it saves the text
to a file and shows a 2,000-character preview (documented at
https://code.claude.com/docs/en/hooks, "capped at 10,000 characters", and
observed: 10/10 replay sessions got the preview, 0 opened the file). So 12 of
13 rules never reached the model, silently.

Independent source of truth
---------------------------
Each rule file's own binding region (``escapement:binding`` markers), read
from the package the host actually ships, and the packaged hook's stdout run
the way a host runs it. The host limit is the documented constant above, not
anything the hook declares.

Invalid solution classes this suite rejects
-------------------------------------------
- Truncating the old concatenation to the limit (later rules vanish)
  -> ``test_every_rules_binding_requirement_reaches_the_session``
- A titles-only index -> same test (asserts the requirement text, not the title)
- A size check that warns but still emits an oversized payload
  -> ``test_oversized_bundle_fails_loud_and_still_fits``
- Summaries hard-coded in the hook (a second source of truth)
  -> ``test_binding_text_comes_from_the_rule_file``
- A rule without a binding region silently dropped
  -> ``test_rule_without_binding_is_named_loudly_with_its_path``
- An index with no way to reach the full rule -> ``test_every_rule_names_its_full_file``
- A broken install failing quietly -> ``test_missing_bundle_still_fails_loud``
- A binding that drops a rule's hard prohibition
  -> ``test_every_bold_prohibition_is_bound_or_explicitly_waived``
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude" / "hooks" / "inject_rules.py"
# Each host package's injector, found where that host runs it; rules are read
# from ``<hook dir>/../rules``.
PACKAGED_HOOKS = {
    "repo": HOOK,
    "claude": ROOT / "plugins" / "escapement-claude" / "hooks" / "inject_rules.py",
    "codex": ROOT / "plugins" / "escapement" / "claude" / "hooks" / "inject_rules.py",
    "pi": ROOT / "plugins" / "escapement-pi" / "claude" / "hooks" / "inject_rules.py",
}

# Claude Code's documented inline cap for a hook's additionalContext.
HOST_INLINE_LIMIT = 10_000

BINDING = re.compile(
    r"<!-- escapement:binding:start -->(.*?)<!-- escapement:binding:end -->", re.S
)


def inject(hook: Path, event: str = "SessionStart") -> str:
    """Run a hook and return the additionalContext it emits."""
    result = subprocess.run(
        [sys.executable, "-B", str(hook)],
        input=json.dumps({"hook_event_name": event, "session_id": "s"}),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return payload["hookSpecificOutput"]["additionalContext"]


def binding_of(path: Path) -> str:
    regions = BINDING.findall(path.read_text(encoding="utf-8"))
    assert len(regions) == 1, f"{path.name}: needs exactly one binding region, has {len(regions)}"
    text = regions[0].strip()
    assert len(text) > 40, f"{path.name}: binding region is too thin to bind anything"
    return text


@pytest.fixture(scope="module", params=sorted(PACKAGED_HOOKS))
def host(request) -> tuple[str, Path]:
    hook = PACKAGED_HOOKS[request.param]
    rules = hook.parent.parent / "rules"
    assert sorted(rules.glob("*.md")), f"{rules} ships no rules"
    return inject(hook), rules


# --- The shipped bundles ---------------------------------------------------

def test_every_rules_binding_requirement_reaches_the_session(host):
    injected, rules = host
    for path in sorted(rules.glob("*.md")):
        assert binding_of(path) in injected, f"{path.name}: binding requirement not injected"


def test_payload_is_inlined_by_the_host_not_saved_to_a_file(host):
    injected, _ = host
    assert len(injected) <= HOST_INLINE_LIMIT, (
        f"injected {len(injected)} chars; Claude Code inlines at most {HOST_INLINE_LIMIT} "
        f"and shows only a 2,000-char preview of anything larger — tighten a binding region"
    )
    assert "[escapement] WARNING" not in injected, (
        "a shipped bundle must fit without the over-budget path"
    )


def test_every_rule_names_its_full_file(host):
    injected, rules = host
    assert str(rules.resolve()) in injected
    for path in sorted(rules.glob("*.md")):
        assert path.name in injected, f"{path.name}: no path to read the full rule"


def test_imperative_framing_survives(host):
    assert "OVERRIDE default behavior" in host[0]


def test_precompact_reinjects_the_same_index():
    assert inject(HOOK, "PreCompact") == inject(HOOK, "SessionStart")


# --- Bindings keep the rules' teeth ----------------------------------------

# Every bolded prohibition in a rule body, and how its binding carries it: a
# phrase that must appear in that rule's binding region, or a waiver saying why
# the agent can safely meet it only on reading the full rule. A new bolded
# prohibition fails this test until someone makes that call.
PROHIBITIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("agent-teams-default.md", '"Roundtable" NEVER means writing simulated dialogue in your output.'):
        ("bound", "never means simulated dialogue"),
    ("agent-teams-default.md", "Subagents do not inherit this rule."):
        ("bound", "Subagents do not inherit"),
    ("continuation-harness.md", 'merge and ship it live. Do NOT ask "want me to merge it now, or review the PR first?"'):
        ("bound", "merge on green without asking"),
    ("continuation-harness.md", "Attempt the merge; do not pre-judge repository authorization in conversation."):
        ("bound", "do not pre-judge"),
    ("molecule-awareness.md", "Do NOT use `bd mol show` to find formulas"):
        ("waived", "formula-authoring procedure; only reached while creating a molecule, "
                   "a task that sends the agent to the full rule"),
    ("outcome-ownership.md", "merge it and ship it live; do not ask."):
        ("bound", "merge it and ship it live; do not ask"),
    ("research-findings-persistence.md", "never the payload."):
        ("bound", "never the payload"),
    ("tdd-enforcement.md", "Lint alone is forbidden as the verification for trigger / auth / deploy-gating changes."):
        ("bound", "Lint alone is forbidden"),
    ("why-drilling.md", "Mark it unconfirmed, name who/what would confirm it, and proceed — do not block."):
        ("bound", "do not block"),
    ("worktree-discipline.md", "never"):
        ("bound", "never the isolation mechanism"),
    ("worktree-discipline.md", "Never"):
        ("bound", "never stash, checkout, clean, or discard WIP you did not write"),
}
_BOLD = re.compile(r"\*\*([^*]+?)\*\*", re.S)
_PROHIBITION = re.compile(r"\b(forbidden|never|must not|do not)\b", re.I)


def bold_prohibitions(rules: Path) -> set[tuple[str, str]]:
    found = set()
    for path in sorted(rules.glob("*.md")):
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        text = BINDING.sub("", text)
        for match in _BOLD.finditer(text):
            phrase = " ".join(match.group(1).split())
            if _PROHIBITION.search(phrase):
                found.add((path.name, phrase))
    return found


def test_every_bold_prohibition_is_bound_or_explicitly_waived():
    rules = ROOT / "claude" / "rules"
    assert bold_prohibitions(rules) == set(PROHIBITIONS), (
        "bolded prohibitions changed — bind each new one or waive it with a reason"
    )
    for (name, _), (kind, value) in PROHIBITIONS.items():
        if kind == "waived":
            assert len(value) >= 40, f"{name}: a waiver needs a real reason"
            continue
        assert value.lower() in binding_of(rules / name).lower(), (
            f"{name}: binding drops the prohibition it must carry ({value!r})"
        )


# --- Synthetic bundles -----------------------------------------------------

def _fake_plugin(tmp_path: Path, files: dict[str, str]) -> Path:
    """A package holding the injector and ``files`` as its rules bundle."""
    root = tmp_path / "plugin"
    (root / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, root / "hooks" / HOOK.name)
    (root / "rules").mkdir()
    for name, body in files.items():
        (root / "rules" / name).write_text(body, encoding="utf-8")
    return root / "hooks" / HOOK.name


def _rule(title: str, binding: str, body: str = "Reference body.\n") -> str:
    return (
        f"# {title}\n\n<!-- escapement:binding:start -->\n{binding}\n"
        f"<!-- escapement:binding:end -->\n\n{body}"
    )


def test_binding_text_comes_from_the_rule_file(tmp_path):
    hook = _fake_plugin(tmp_path, {
        "zebra.md": _rule("Zebra Rule", "Always paint the stripes before the hooves dry."),
    })
    context = inject(hook)
    assert "Always paint the stripes before the hooves dry." in context
    assert "Zebra Rule" in context


def test_reference_body_stays_on_disk(tmp_path):
    hook = _fake_plugin(tmp_path, {
        "a.md": _rule("A", "Do the binding thing every single time it applies.",
                      "A long worked example that only matters once you are in it.\n"),
    })
    assert "only matters once you are in it" not in inject(hook)


def test_rule_without_binding_is_named_loudly_with_its_path(tmp_path):
    hook = _fake_plugin(tmp_path, {"plain.md": "# Plain Rule\n\nDo the thing.\n"})
    context = inject(hook)
    assert "WARNING" in context
    assert "Plain Rule" in context and "plain.md" in context


def test_oversized_bundle_fails_loud_and_still_fits(tmp_path):
    files = {
        f"r{n:02}.md": _rule(f"Rule {n}", f"Requirement {n}: " + "x" * 900)
        for n in range(20)
    }
    context = inject(_fake_plugin(tmp_path, files))
    assert len(context) <= HOST_INLINE_LIMIT, "over-budget output must still be inlined"
    # The warning must land inside the 2,000-char preview a host would show.
    assert "WARNING" in context[:2000]
    assert "r19.md" in context, "every rule must stay reachable by path"


def test_missing_bundle_still_fails_loud(tmp_path):
    """A broken install must be visible, not a silently ruleless session."""
    context = inject(_fake_plugin(tmp_path, {}))
    assert "WARNING" in context and "NOT injected" in context
