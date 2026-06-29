"""Tests for the LIVE wind-down rung: inline judge, outage sentinel, and git-aware
work-remains. Companion to test_winddown_stop_integration.py (which covers the
already-wired cached-verdict path).

Two new behaviours, both load-bearing:

  1. INLINE JUDGE (lights up the local model live, no daemon). When there is NO
     fresh cached verdict AND reversible work remains, the Stop hook runs the
     local-LLM judge inline (bounded timeout, fail-open) and writes the verdict to
     winddown_verdict.json. This is exactly the slice the cake veiled-stop exposed:
     no monitor existed, so no semantic verdict was available.

  2. GIT-AWARE WORK-REMAINS. "Reversible work remains" must include unpushed
     commits / dirty tracked files, not only beads. The cake stop claimed
     "nothing outstanding" with 4 unpushed commits and a drained bead queue.

The oracle that keeps this honest: the judge must NOT run when no work remains
(bounds latency + prevents nagging a legitimate stop), and a judge outage must be
observable before the narrow deterministic outage sentinel can block known shapes.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh  # noqa: E402


def _write_transcript(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return str(p)


def _asst(text, **extra):
    d = {"type": "assistant", "message": {"role": "assistant", "content": text}}
    d.update(extra)
    return d


def _work_remains(cwd, thread_dir=None):
    return ("block", "implicit_queue_scoped")


def _no_work(cwd, thread_dir=None):
    return ("allow", "implicit_queue_scoped_drained")


# A veiled-stop offer. Post-refactor (judge-only) there is no regex floor, so the
# judge is consulted for EVERY conversational stop with work remaining — this string
# is just a representative offer the injected judge classifies. (Kept the name for
# diff continuity; it no longer implies a regex blind spot.)
_REGEX_BLIND_OFFER = "Everything's in a good state and there's nothing pressing left to do here."

_DWDEV_FINAL_WINDDOWN = (
    "Branch state: DWDEV-11304-churn-dashboard-risk-logic on origin, 2 commits, "
    "design complete. No PR yet.\n\n"
    "Open follow-ups when you want them (none blocking):\n"
    "1. Author the remaining OpenSpec artifacts -- specs/ capability deltas + "
    "tasks.md + test-oracle-brief -- then it's ready for implementation.\n"
    "2. The deferred archive of the old churn-dashboard-data-quality change.\n"
    "3. Open a PR for DWDEV-11304 (draft, since implementation hasn't started).\n\n"
    "Want any of those, or is this a good stopping point?"
)

_DWDEV_EARLY_WINDDOWN = (
    "The worktree lives at .worktrees/churn-dashboard-risk-logic if you want to "
    "keep drafting there. Want me to open a draft PR for DWDEV-11304, finish the "
    "remaining design.md sections, or save a memory of the gone-dark finding + "
    "this change so a future session picks up cleanly?"
)


def test_regex_floor_is_removed():
    # Architecture guard (replaces test_regex_blind_offer_is_actually_regex_blind):
    # the regex floor is KILLED. is_winddown_offer must no longer exist on the gate
    # module — the judge is the sole classifier.
    import winddown_gate as wg
    assert not hasattr(wg, "is_winddown_offer"), (
        "is_winddown_offer (regex floor) must be removed — classification is judge-only"
    )


# ---------------------------------------------------------------------------
# Inline judge — runs ONLY in the narrow slice (regex-miss + work-remains + cold cache)
# ---------------------------------------------------------------------------

def test_inline_judge_blocks_regex_blind_offer_when_model_flags_it(tmp_path):
    """The model catches what the regex missed → BLOCK (recall the cake case)."""
    calls = []

    def spy_judge(text):
        calls.append(text)
        return True  # model: this IS a wind-down

    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=spy_judge,
    )
    assert disp is not None and "proceed" in disp.lower()
    assert calls == [_REGEX_BLIND_OFFER]  # judge actually consulted


def test_inline_judge_writes_verdict_cache(tmp_path):
    """A computed verdict is persisted (warms cache / observability / future monitor)."""
    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=lambda t: True,
    )
    cached = json.loads((tmp_path / "winddown_verdict.json").read_text())
    assert cached["verdict"] is True and "ts" in cached


def test_judge_IS_consulted_for_obvious_offer_no_regex_preempt(tmp_path):
    """REPLACES test_inline_judge_NOT_called_when_regex_already_caught_it.

    Under judge-only there is no regex to pre-empt the judge. Even for an obvious
    wrap offer that the OLD regex floor would have caught for free, the judge is now
    the SOLE classifier and MUST be consulted (cold cache + work remains). The block
    comes from the judge's verdict, not a regex. A surviving-regex impl would
    short-circuit here and leave the judge uncalled — which this test rejects."""
    calls = []

    def spy_judge(text):
        calls.append(text)
        return True  # judge: this IS a wind-down

    tp = _write_transcript(tmp_path, [_asst("want me to wrap for the night, or keep going?")])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=spy_judge,
    )
    assert disp is not None, "judge flagged the offer + work remains → must block"
    assert calls == ["want me to wrap for the night, or keep going?"], (
        "judge-only: the judge MUST be consulted even for an obvious wrap offer "
        f"(no regex pre-empt); calls={calls}"
    )


def test_inline_judge_NOT_called_when_no_work_remains(tmp_path):
    """Fragile-impl reject: no reversible work → legitimate stop. Never spend a
    judge call, never nag."""
    calls = []

    def spy_judge(text):
        calls.append(text)
        return True

    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_no_work, judge=spy_judge,
    )
    assert disp is None
    assert calls == []


def test_inline_judge_fail_open_when_model_errors(tmp_path):
    """Judge raises → ALLOW for non-sentinel text. A judge problem must never block or
    crash the hook unless the separate high-confidence outage sentinel recognizes a
    transcript-proven shape."""
    def boom_judge(text):
        raise RuntimeError("model down")

    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=boom_judge,
    )
    assert disp is None  # judge errored, no regex floor → no block (fail-open, not fabricated)


def test_fail_open_emits_judge_unavailable_signal(tmp_path, monkeypatch):
    """NEW (gate-design Rule 2 / F5-class): when the judge is unavailable but work
    remains, the fail-open ALLOW must NOT be silent — a `winddown_judge_unavailable`
    signal must be recorded so judge outages are visible in the corpus (not an
    invisible hole, the same class as the R3 ImportError fail-open).

    Observable seam: the incidents log. We redirect sh.INCIDENTS_LOG to a tmp file
    and assert a record carrying the unavailable reason lands. The judge returns None
    (unclear/down) WITH reversible work remaining — the exact slice that must signal.

    This is RED until the production fail-open path emits the signal; the current
    code allows silently."""
    incidents = tmp_path / "incidents.jsonl"
    monkeypatch.setattr(sh, "INCIDENTS_LOG", incidents)
    # Avoid touching the real .beads/.gate-signal store from the bridge.
    monkeypatch.setenv("GATE_SIGNAL_FALLBACK_DIR", str(tmp_path / "sig"))

    def unavailable_judge(text):
        return None  # judge down / unclear → fail-open

    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, str(tmp_path), tmp_path,
        work_check=_work_remains, judge=unavailable_judge,
    )
    assert disp is None, "judge unavailable → fail-open allow (no block)"

    assert incidents.exists(), (
        "fail-open on an unavailable judge must record a signal, not stop silently "
        "(gate-design Rule 2) — no incidents file was written"
    )
    body = incidents.read_text()
    assert "winddown_judge_unavailable" in body, (
        "the fail-open must be labeled `winddown_judge_unavailable` in the corpus so "
        f"judge outages are countable; incidents body was: {body!r}"
    )


def test_judge_unavailable_blocks_high_confidence_dwdev_winddown(tmp_path):
    """Regression for DWDEV-11304: Claude Stop hooks ran, the judge outage path
    allowed, and the final assistant message asked whether to stop with concrete
    follow-ups still reversible. The outage sentinel is intentionally scoped to
    this high-confidence wind-down shape; it is not a replacement classifier."""
    for text in (_DWDEV_FINAL_WINDDOWN, _DWDEV_EARLY_WINDDOWN):
        tp = _write_transcript(tmp_path, [_asst(text)])
        disp = sh._winddown_override(
            "conversational", tp, str(tmp_path), tmp_path,
            work_check=_work_remains, judge=lambda t: None,
        )
        assert disp is not None and "proceed" in disp.lower()


def test_judge_unavailable_sentinel_ignores_non_winddown_stop_words(tmp_path):
    """Negative controls for the tempting shortcut: work remains + judge None
    must not block ordinary technical prose just because it contains stop-ish
    words or a choice question."""
    non_winddowns = [
        "Should I use Postgres or SQLite for this service?",
        "The loop's stopping condition should be None when the stream closes.",
        "From this point I will continue with the PR checks and implementation.",
    ]
    for text in non_winddowns:
        tp = _write_transcript(tmp_path, [_asst(text)])
        disp = sh._winddown_override(
            "conversational", tp, str(tmp_path), tmp_path,
            work_check=_work_remains, judge=lambda t: None,
        )
        assert disp is None


def test_judge_negative_verdict_overrides_high_confidence_sentinel(tmp_path):
    """The deterministic sentinel is only for an unavailable judge. If the model
    returns a real negative verdict, model ownership still allows."""
    tp = _write_transcript(tmp_path, [_asst(_DWDEV_FINAL_WINDDOWN)])
    disp = sh._winddown_override(
        "conversational", tp, str(tmp_path), tmp_path,
        work_check=_work_remains, judge=lambda t: False,
    )
    assert disp is None


def test_cached_verdict_short_circuits_inline_judge(tmp_path):
    """A fresh cached verdict (a future monitor's output) is used instead of
    spawning the inline judge."""
    calls = []

    def spy_judge(text):
        calls.append(text)
        return True

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "winddown_verdict.json").write_text(json.dumps({"verdict": True, "ts": now}))
    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=spy_judge,
    )
    assert disp is not None    # blocked via the cached verdict
    assert calls == []         # inline judge not spawned


# ---------------------------------------------------------------------------
# Git-aware work-remains — real git repos (not mocks), to avoid an echo test
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t.t")
    _git(path, "config", "user.name", "t")
    return path


def test_git_work_remains_false_on_clean_pushed_repo(tmp_path):
    """Negative control: clean tree, nothing ahead of upstream → no git work."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    repo = _init_repo(tmp_path / "wt")
    (repo / "f.txt").write_text("hello")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    assert sh._git_work_remains(str(repo)) is False


def test_git_work_remains_true_on_unpushed_commit(tmp_path):
    """Positive control — the CAKE failure: clean tree, but a commit not pushed
    to upstream. A status-only check (missing ahead-of-upstream) would FAIL this."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    repo = _init_repo(tmp_path / "wt")
    (repo / "f.txt").write_text("hello")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    # a second commit, NOT pushed
    (repo / "g.txt").write_text("more")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "unpushed")
    assert sh._git_work_remains(str(repo)) is True


def test_git_work_remains_true_on_dirty_tracked_file(tmp_path):
    """Positive control: an uncommitted modification to a tracked file."""
    repo = _init_repo(tmp_path / "wt")
    (repo / "f.txt").write_text("hello")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    (repo / "f.txt").write_text("changed")  # dirty, tracked
    assert sh._git_work_remains(str(repo)) is True


def test_git_work_remains_false_on_untracked_only(tmp_path):
    """Pure untracked files (scratch/artifacts) do NOT count — they are noise and
    counting them would nag nearly every stop in a working repo. Deliberate scope."""
    repo = _init_repo(tmp_path / "wt")
    (repo / "f.txt").write_text("hello")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    (repo / "scratch.tmp").write_text("artifact")  # untracked only
    assert sh._git_work_remains(str(repo)) is False


def test_git_work_remains_false_outside_git_repo(tmp_path):
    """Fail-open: not a git repo → False (never fabricate work, never crash)."""
    assert sh._git_work_remains(str(tmp_path)) is False


def test_git_work_remains_false_on_bad_cwd():
    """Fail-open: nonexistent cwd → False, no exception."""
    assert sh._git_work_remains("/nonexistent/path/xyz") is False


def test_git_flips_bd_drained_to_block_in_override(tmp_path):
    """End-to-end: bd queue drained, but an unpushed commit + a regex-caught
    wind-down offer → the override BLOCKS via the git work-remains source."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    repo = _init_repo(tmp_path / "wt")
    (repo / "f.txt").write_text("hello")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    (repo / "g.txt").write_text("more")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "unpushed")

    tp = _write_transcript(tmp_path, [_asst("want me to wrap for the night, or keep going?")])
    disp = sh._winddown_override(
        "conversational", tp, str(repo), tmp_path,
        work_check=_no_work,        # beads says nothing left
        judge=lambda t: True,       # judge-only: the verdict must be supplied (no regex)
    )
    assert disp is not None  # git work-remains flips it to block (verdict says offer)
