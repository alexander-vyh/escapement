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
# span of the requirement that must appear in that rule's binding region, or a
# waiver saying why the agent can safely meet it only on reading the full rule.
# A new bolded prohibition fails this test until someone makes that call. Where
# only a word or two is bolded ("Do **not** pick up..."), the key is the whole
# sentence around it.
PROHIBITIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("agent-teams-default.md", '"Roundtable" NEVER means writing simulated dialogue in your output.'):
        ("bound", '"roundtable" never means simulated dialogue in your output'),
    ("agent-teams-default.md", "- **Always pair** for feature/epic work with behavioral specs - **Consider pairing** for complex bug fixes where the fix could mask the root cause - **Skip pairing** for simple chores, config changes, one-liners"):
        ("bound", "Always pair feature/epic implementation with an independent reviewing agent"),
    ("agent-teams-default.md", "A blocked agent is not a blocked team."):
        ("bound", "A blocked agent is not a blocked team: escalate the narrow choice"),
    ("agent-teams-default.md", "Most research does NOT need this."):
        ("waived", "qualifies the opt-in vocab-scout guidance; it narrows an optional "
                   "practice and imposes nothing on the agent"),
    ("agent-teams-default.md", "Subagents do not inherit this rule."):
        ("bound", "Subagents do not inherit these rules: put the continuation discipline in every agent prompt"),
    ("continuation-harness.md", "Attempt the merge; do not pre-judge repository authorization in conversation."):
        ("bound", "Attempt the merge; do not pre-judge repository authorization"),
    ("continuation-harness.md", "Do **not** pick up unrelated ready tasks from `bd ready` to drain the queue and satisfy the gate."):
        ("bound", "Do not pick up unrelated `bd ready` tasks to drain the queue and satisfy the gate"),
    ("continuation-harness.md", "On re-invocation, classify the run mechanically — do NOT do manual `ps`/file-activity forensics:"):
        ("waived", "background-workflow watchdog procedure; only reached while running "
                   "a watched background workflow, which sends the agent to the full rule"),
    ("continuation-harness.md", 'The "irreversible external action" carve-out does NOT cover a merge that triggers auto-deploy.'):
        ("bound", "The irreversible-external-action carve-out does not cover a merge that triggers auto-deploy"),
    ("continuation-harness.md", 'merge and ship it live. Do NOT ask "want me to merge it now, or review the PR first?"'):
        ("bound", "`auto_merge_on_green: true`, merge on green without asking"),
    ("delicate-art-of-bureaucracy.md", "Coercion is a smell, not a strategy."):
        ("bound", "A gate that only blocks, with no affordance to unblock, is coercive"),
    ("delicate-art-of-bureaucracy.md", "Design intent does not survive implementation."):
        ("waived", "an observation about how gates are experienced once shipped; it "
                   "explains the rule rather than forbidding an action"),
    ("gate-design.md", "Validate value, not presence."):
        ("bound", "(3) validate value, not presence"),
    ("molecule-awareness.md", "Do NOT use `bd mol show` to find formulas"):
        ("waived", "formula-authoring procedure; only reached while creating a molecule, "
                   "a task that sends the agent to the full rule"),
    ("molecule-awareness.md", "Scope changes are always human-driven."):
        ("bound", "Scope changes are always human-driven: never silently change scope, specifications, or task descriptions"),
    ("outcome-ownership.md", "Closing every child is an intermediate artifact, not the parent's outcome"):
        ("bound", "not code that compiles, tests that pass, or children that closed"),
    ("outcome-ownership.md", "merge it and ship it live; do not ask."):
        ("bound", "Where `.escapement/repo.json` authorizes it, merge it and ship it live; do not ask"),
    ("research-findings-persistence.md", "never the payload."):
        ("bound", "its message is a pointer to that file, never the payload"),
    ("tdd-enforcement.md", "Lint alone is forbidden as the verification for trigger / auth / deploy-gating changes."):
        ("bound", "Lint alone is forbidden as the verification for trigger / auth / deploy-gating changes"),
    ("tdd-enforcement.md", "gates, not oracles"):
        ("bound", "Lint alone is forbidden as the verification"),
    ("tdd-enforcement.md", "structured waiver, not an exemption"):
        ("bound", "file a structured waiver that names the post-merge observation"),
    ("why-drilling.md", "Mark it unconfirmed, name who/what would confirm it, and proceed — do not block."):
        ("bound", "mark it unconfirmed, name who or what would confirm it, and proceed — do not block"),
    ("why-drilling.md", "floor, not a ceiling."):
        ("waived", "scopes the probe (deeper drilling is opt-in elsewhere); it limits "
                   "the rule rather than adding a requirement"),
    ("worktree-discipline.md", "**Never** `git stash`, `git checkout`, `git clean`, or discard when the tree holds WIP you did not write — that destroys another writer's work."):
        ("bound", "never stash, checkout, clean, or discard WIP you did not write"),
    ("worktree-discipline.md", 'Prompt-level "you own these files" lanes are merge-planning notes, **never** the isolation mechanism; compliance-based lanes have leaked in practice.'):
        ("bound", "prompt-level file lanes are never the isolation mechanism"),
}
_BOLD = re.compile(r"\*\*([^*]+?)\*\*")
_PROHIBITION = re.compile(r"\b(forbidden|never|must not|do not|does not|not|always)\b", re.I)
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# A bound span must be long enough that gutting the requirement around a short
# phrase ("do not block") still fails.
MIN_BOUND_SPAN = 30


def _prose(text: str) -> str:
    """Rule text outside its binding region and fenced code."""
    out, fenced = [], False
    for line in BINDING.sub("", text).splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            out.append(line)
    return "\n".join(out)


def bold_prohibitions(rules: Path) -> set[tuple[str, str]]:
    found = set()
    for path in sorted(rules.glob("*.md")):
        for para in re.split(r"\n\s*\n", _prose(path.read_text(encoding="utf-8"))):
            flat = " ".join(para.split())
            for match in _BOLD.finditer(flat):
                bold = match.group(1).strip()
                if not _PROHIBITION.search(bold):
                    continue
                if len(bold.split()) > 2:
                    found.add((path.name, bold))
                    continue
                ends = [e.end() for e in _SENTENCE_END.finditer(flat, 0, match.start())]
                after = _SENTENCE_END.search(flat, match.end())
                sentence = flat[ends[-1] if ends else 0:after.end() if after else len(flat)]
                found.add((path.name, sentence.strip()))
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
        assert len(value) >= MIN_BOUND_SPAN, f"{name}: bound span too short to prove anything"
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
