"""Unit tests for discovery-close-gate.py (modernized, openspec-aware).

The hook fires on `bd close`, finds the relevant design (openspec/changes/{name}/
primary, docs/plans/ legacy fallback), and surfaces four things as an "ask":
  - proof of delivery
  - anti-metrics
  - walking skeleton task count > 3
  - unresolved [SKELETON-BLOCKING] open questions

It is advisory only — always exit 0 (ask or silent allow), never deny.

Run from anywhere with:
  python -m pytest claude/hooks/tests/test_discovery_close_gate.py -v
"""

import importlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_hooks_dir = Path(__file__).resolve().parents[1]

if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

# The hook file has a hyphen in its name — import by file path.
_MOD_PATH = _hooks_dir / "discovery-close-gate.py"


def _import_hook():
    spec = importlib.util.spec_from_file_location("discovery_close_gate", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DESIGN_FULL = """# Design — my-feature

## Riskiest Assumption
We are betting the email flow covers 90% of cases.

## Walking Skeleton
- Convert the password-reset page end to end
- Capture a baseline of reset success rate
- Observe for one week

## Proof of Delivery
I will know this is worth continuing when reset support tickets drop after the
skeleton ships.

## Anti-Metrics
Even if this works perfectly, it has failed if users bypass it and email support
directly.

## Open Questions
- [DEFERRABLE] Should we localize the reset email in phase 2?
"""

DESIGN_OVERSIZED_SKELETON = """# Design — big-feature

## Walking Skeleton
- Pre-flight verification
- Convert page one
- Convert page two
- Capture baseline
- Observe for a week
- Phase 1 review meeting

## Proof of Delivery
I will know this is worth continuing when the conversions land cleanly.
"""

DESIGN_BLOCKING_OQ = """# Design — blocked-feature

## Walking Skeleton
- Convert the shared header
- Observe for a week

## Open Questions
- [SKELETON-BLOCKING] Which Vuex stores does the shared header consume?
- [DEFERRABLE] Should there be a numeric escape-hatch cap?
"""

DESIGN_CLEAN = """# Design — tidy-feature

## Riskiest Assumption
We are betting the cache invalidation strategy holds.

## Walking Skeleton
- Wire the cache-busting header
- Verify a stale read no longer occurs
"""

TASKS_OVERSIZED = """# Tasks — big-feature

- [ ] Pre-flight verification
- [ ] Convert page one
- [ ] Convert page two
- [ ] Capture baseline
- [ ] Observe for a week
- [ ] Phase 1 review
"""

TASKS_OK = """# Tasks — my-feature

- [ ] Convert the password-reset page end to end
- [ ] Capture a baseline of reset success rate
- [ ] Observe for one week
"""


def _make_openspec_change(tmpdir, name="my-feature", design=None, tasks=None):
    """Create openspec/changes/{name}/ with optional design.md and tasks.md.

    Returns the project root (the dir to pass as cwd).
    """
    change_dir = Path(tmpdir) / "openspec" / "changes" / name
    change_dir.mkdir(parents=True)
    if design is not None:
        (change_dir / "design.md").write_text(design)
    if tasks is not None:
        (change_dir / "tasks.md").write_text(tasks)
    return str(tmpdir)


def _make_legacy_doc(tmpdir, name="2026-05-14-thing-design.md", content=""):
    """Create docs/plans/{name}. Returns the project root."""
    plans = Path(tmpdir) / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / name).write_text(content)
    return str(tmpdir)


def _install_fake_bd(root, bead_links):
    """Put a `bd` on PATH whose `show <id> --json` carries that bead's link.

    The gate resolves a design from the bead's own record, so a test that wants
    questions has to say which design the closing bead belongs to. That is the
    contract: a bead with no link has no design to be verified against.
    """
    bin_dir = Path(root) / "fake-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "bd"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"LINKS = json.loads({json.dumps(bead_links)!r})\n"
        "args = sys.argv[1:]\n"
        "if len(args) >= 2 and args[0] == 'show' and args[1] in LINKS:\n"
        "    print(json.dumps([{'id': args[1], 'description': LINKS[args[1]]}]))\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    script.chmod(0o755)
    return str(bin_dir)


def _run_hook(hook_event="PreToolUse", tool_name="Bash", command="bd close my-1",
              cwd="", raw_stdin=None, session_id=None, bead_links=None):
    """Run the hook's main() and return (exit_code, stdout)."""
    mod = _import_hook()
    if raw_stdin is None:
        payload = {"hook_event_name": hook_event, "tool_name": tool_name,
                   "tool_input": {"command": command}}
        if cwd:
            payload["cwd"] = cwd
        if session_id is not None:
            payload["session_id"] = session_id
        stdin_data = json.dumps(payload)
    else:
        stdin_data = raw_stdin

    env = {}
    if bead_links:
        bin_dir = _install_fake_bd(cwd or ".", bead_links)
        env["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    out = io.StringIO()
    try:
        with patch.dict(os.environ, env), patch("sys.stdin", io.StringIO(stdin_data)), \
                patch("sys.stdout", out):
            mod.main()
        return 0, out.getvalue()
    except SystemExit as exc:
        return exc.code, out.getvalue()


def _decision(stdout):
    if not stdout.strip():
        return None
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]


def _reason(stdout):
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


# ===========================================================================
# Pure function: count_list_items
# ===========================================================================

class TestCountListItems:
    def test_counts_dash_items(self):
        mod = _import_hook()
        assert mod.count_list_items("- a\n- b\n- c") == 3

    def test_counts_checkbox_items(self):
        mod = _import_hook()
        assert mod.count_list_items("- [ ] a\n- [ ] b") == 2

    def test_counts_numbered_items(self):
        mod = _import_hook()
        assert mod.count_list_items("1. a\n2. b") == 2

    def test_ignores_indented_subitems(self):
        mod = _import_hook()
        assert mod.count_list_items("- top\n  - sub\n  - sub2\n- top2") == 2

    def test_ignores_non_list_lines(self):
        mod = _import_hook()
        assert mod.count_list_items("# Heading\n\nsome prose\n- one item") == 1


# ===========================================================================
# Pure function: designs_in_blob (which design a bead's record points at)
# ===========================================================================

class TestDesignsInBlob:
    def test_resolves_an_openspec_reference(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="feat-a", design=DESIGN_CLEAN)
            found = mod.designs_in_blob(
                '{"description": "see openspec/changes/feat-a/design.md"}', Path(root))
        assert [p.parent.name for p in found] == ["feat-a"]

    def test_resolves_a_legacy_plans_reference(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_legacy_doc(tmp, name="old-design.md", content=DESIGN_FULL)
            found = mod.designs_in_blob(
                '{"notes": "docs/plans/old-design.md"}', Path(root))
        assert [p.name for p in found] == ["old-design.md"]

    def test_ignores_the_archive_and_unresolvable_references(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="feat-a", design=DESIGN_CLEAN)
            (Path(root) / "openspec" / "changes" / "archive").mkdir()
            blob = ('{"description": "openspec/changes/archive/old-thing/design.md '
                    'and openspec/changes/never-existed/design.md"}')
            assert mod.designs_in_blob(blob, Path(root)) == []

    def test_a_record_naming_no_design_resolves_nothing(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="feat-a", design=DESIGN_CLEAN)
            assert mod.designs_in_blob('{"title": "bump a pin"}', Path(root)) == []


# ===========================================================================
# Pure function: count_skeleton_tasks
# ===========================================================================

class TestCountSkeletonTasks:
    def test_counts_from_tasks_md(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OVERSIZED)
            change_dir = Path(root) / "openspec" / "changes" / "my-feature"
            assert mod.count_skeleton_tasks(str(change_dir)) == 6

    def test_falls_back_to_design_walking_skeleton(self):
        """No tasks.md -> count list items in design.md's Walking Skeleton."""
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=None)
            change_dir = Path(root) / "openspec" / "changes" / "my-feature"
            assert mod.count_skeleton_tasks(str(change_dir)) == 3

    def test_none_when_no_skeleton_anywhere(self):
        mod = _import_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design="# Design\n\nNo skeleton here.",
                                         tasks=None)
            change_dir = Path(root) / "openspec" / "changes" / "my-feature"
            assert mod.count_skeleton_tasks(str(change_dir)) is None


# ===========================================================================
# Pure function: find_skeleton_blocking_oqs
# ===========================================================================

class TestFindSkeletonBlockingOqs:
    def test_finds_blocking_entries(self):
        mod = _import_hook()
        result = mod.find_skeleton_blocking_oqs(DESIGN_BLOCKING_OQ)
        assert len(result) == 1
        assert "Vuex stores" in result[0]

    def test_deferrable_only_returns_empty(self):
        mod = _import_hook()
        assert mod.find_skeleton_blocking_oqs(DESIGN_FULL) == []

    def test_no_open_questions_section_returns_empty(self):
        mod = _import_hook()
        assert mod.find_skeleton_blocking_oqs(DESIGN_CLEAN) == []


# ===========================================================================
# Hook behavior — fast-path allows
# ===========================================================================

class TestFastPathAllows:
    def test_non_pretooluse_allows(self):
        code, out = _run_hook(hook_event="PostToolUse")
        assert code == 0 and out == ""

    def test_non_bash_allows(self):
        code, out = _run_hook(tool_name="Write")
        assert code == 0 and out == ""

    def test_non_bd_close_allows(self):
        code, out = _run_hook(command="bd list")
        assert code == 0 and out == ""

    def test_the_phrase_inside_quoted_prose_is_not_a_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd note my-1 \"blocked because bd close my-1 is gated\"",
                cwd=root,
                bead_links={"my-1": "openspec/changes/my-feature/design.md"},
            )
        assert code == 0 and out == ""

    def test_bd_close_no_design_anywhere_allows_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run_hook(command="bd close x-1", cwd=tmp)
        assert code == 0 and out == ""

    def test_a_bead_linking_no_design_allows_even_when_designs_exist(self):
        """The defect: the gate used to ask about the newest change dir instead."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close pins-1",
                cwd=root,
                bead_links={"pins-1": "re-enable the AIR3xx lints"},
            )
        assert code == 0 and out == ""

    def test_invalid_json_allows(self):
        code, _ = _run_hook(raw_stdin="not json")
        assert code == 0


# ===========================================================================
# Hook behavior — openspec change (primary path)
# ===========================================================================

class TestOpenspecChange:
    def test_proof_and_anti_metrics_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close my-1", cwd=root,
                bead_links={"my-1": "openspec/changes/my-feature/design.md"})
        assert code == 0
        assert _decision(out) == "ask"
        reason = _reason(out)
        assert "worth continuing" in reason  # proof of delivery
        assert "bypass it" in reason         # anti-metric

    def test_oversized_skeleton_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="big-feature",
                                         design=DESIGN_OVERSIZED_SKELETON,
                                         tasks=TASKS_OVERSIZED)
            code, out = _run_hook(
                command="bd close big-1", cwd=root,
                bead_links={"big-1": "openspec/changes/big-feature/design.md"})
        assert code == 0
        assert _decision(out) == "ask"
        reason = _reason(out)
        assert "6" in reason and "skeleton" in reason.lower()

    def test_well_sized_skeleton_does_not_flag_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close my-1", cwd=root,
                bead_links={"my-1": "openspec/changes/my-feature/design.md"})
        # proof + anti-metrics still surface, but not a skeleton-size complaint
        reason = _reason(out) if out.strip() else ""
        assert "the rule is 1-3" not in reason

    def test_skeleton_blocking_oq_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="blocked-feature",
                                         design=DESIGN_BLOCKING_OQ)
            code, out = _run_hook(
                command="bd close blk-1", cwd=root,
                bead_links={"blk-1": "openspec/changes/blocked-feature/design.md"})
        assert code == 0
        assert _decision(out) == "ask"
        reason = _reason(out)
        assert "SKELETON-BLOCKING" in reason
        assert "Vuex stores" in reason

    def test_deferrable_oq_does_not_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close my-1", cwd=root,
                bead_links={"my-1": "openspec/changes/my-feature/design.md"})
        reason = _reason(out) if out.strip() else ""
        assert "SKELETON-BLOCKING" not in reason

    def test_clean_design_allows_silently(self):
        """A design with no proof/anti-metrics/oversize/blocking-OQ -> silent allow."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="tidy-feature",
                                         design=DESIGN_CLEAN, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close tidy-1", cwd=root,
                bead_links={"tidy-1": "openspec/changes/tidy-feature/design.md"})
        assert code == 0
        assert out == ""

    def test_multiple_findings_combine_into_one_ask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="big-feature",
                                         design=DESIGN_OVERSIZED_SKELETON,
                                         tasks=TASKS_OVERSIZED)
            code, out = _run_hook(
                command="bd close big-1", cwd=root,
                bead_links={"big-1": "openspec/changes/big-feature/design.md"})
        assert code == 0
        reason = _reason(out)
        # proof of delivery AND oversized skeleton both present
        assert "worth continuing" in reason
        assert "skeleton" in reason.lower()

    def test_never_denies(self):
        """Even with every finding present, the hook asks — never denies."""
        design = DESIGN_OVERSIZED_SKELETON + DESIGN_BLOCKING_OQ + (
            "\n## Anti-Metrics\nEven if this works perfectly, it has failed if "
            "latency exceeds 2s.\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, name="kitchen-sink",
                                         design=design, tasks=TASKS_OVERSIZED)
            code, out = _run_hook(
                command="bd close ks-1", cwd=root,
                bead_links={"ks-1": "openspec/changes/kitchen-sink/design.md"})
        assert code == 0
        assert _decision(out) == "ask"


# ===========================================================================
# Hook behavior — legacy docs/plans/ designs
# ===========================================================================

class TestLegacyPlansDesign:
    def test_a_bead_linking_a_legacy_design_doc_is_asked_about(self):
        """docs/plans/ is still a real design link, not just an openspec one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_legacy_doc(tmp, content=DESIGN_FULL)
            code, out = _run_hook(
                command="bd close leg-1", cwd=root,
                bead_links={"leg-1": "docs/plans/2026-05-14-thing-design.md"})
        assert code == 0
        assert _decision(out) == "ask"
        assert "worth continuing" in _reason(out)

    def test_the_bead_selects_its_design_rather_than_a_directory_precedence(self):
        """An unrelated openspec change must not displace the linked plan doc.

        The old hook preferred openspec/changes/ wholesale and ignored the plan
        doc; whichever directory won, neither answer was about the closing bead.
        """
        with tempfile.TemporaryDirectory() as tmp:
            change_dir = Path(tmp) / "openspec" / "changes" / "tidy-feature"
            change_dir.mkdir(parents=True)
            (change_dir / "design.md").write_text(DESIGN_CLEAN)
            (change_dir / "tasks.md").write_text(TASKS_OK)
            plans = Path(tmp) / "docs" / "plans"
            plans.mkdir(parents=True)
            (plans / "old-design.md").write_text(DESIGN_FULL)
            code, out = _run_hook(
                command="bd close t-1", cwd=tmp,
                bead_links={"t-1": "docs/plans/old-design.md"})
        assert code == 0
        assert _decision(out) == "ask"
        reason = _reason(out)
        assert "old-design.md" in reason
        assert "tidy-feature" not in reason


# ===========================================================================
# Escape and dedup: the gate must be answerable (escapement-kdrc)
# ===========================================================================

_MY_FEATURE_LINK = {"mine-1": "openspec/changes/my-feature/design.md"}


class TestInlineWaiver:
    def test_waiver_with_substantive_reason_allows(self):
        """THE ESCAPE: a close whose linked design cannot honestly be answered
        (superseded, rolled back) must be able to proceed, reason recorded."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close mine-1  # close-gate-waiver: the shipped work was rolled back in the incident review, so there is no delivery to verify",
                cwd=root,
                bead_links=_MY_FEATURE_LINK,
            )
        assert code == 0
        assert out == ""  # silent allow, not an ask

    def test_waiver_with_short_reason_still_asks(self):
        """A waiver is an escape, not a magic word: the reason must be substantive."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(
                command="bd close mine-1  # close-gate-waiver: because",
                cwd=root,
                bead_links=_MY_FEATURE_LINK,
            )
        assert code == 0
        assert _decision(out) == "ask"

    def test_ask_message_names_the_waiver_escape(self):
        """REPAIR: the ask itself must teach the way out, or it is a dead end."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            code, out = _run_hook(command="bd close mine-1", cwd=root,
                                  session_id="esc-no-hint", bead_links=_MY_FEATURE_LINK)
        assert code == 0
        assert "close-gate-waiver" in _reason(out)


class TestDedupRegression:
    def test_same_session_id_asks_once_then_allows(self):
        """THE DEFECT (escapement-kdrc): the Pi adapter keyed session_id on the
        per-call toolCallId, so the ask-once dedup never engaged and every
        closing attempt blocked forever. With a stable session id, the second
        attempt proceeds — ask once, answer, continue."""
        sid = "esc-dedup-regression"
        state = Path(tempfile.gettempdir()) / f"discovery_close_gate_{sid}.json"
        state.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
                _, first = _run_hook(command="bd close mine-1", cwd=root,
                                     session_id=sid, bead_links=_MY_FEATURE_LINK)
                assert _decision(first) == "ask"
                code, second = _run_hook(command="bd close mine-1", cwd=root,
                                         session_id=sid, bead_links=_MY_FEATURE_LINK)
            assert code == 0
            assert second == ""
        finally:
            state.unlink(missing_ok=True)

    def test_without_session_id_asks_every_time(self):
        """Pins the fail-loud default: no session identity means no dedup.
        Adapters that supply no id get the question every time — visible,
        not silently suppressed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_openspec_change(tmp, design=DESIGN_FULL, tasks=TASKS_OK)
            for _ in range(2):
                code, out = _run_hook(command="bd close mine-1", cwd=root,
                                      bead_links=_MY_FEATURE_LINK)
                assert code == 0
                assert _decision(out) == "ask"
