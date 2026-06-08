"""Tests for the LIVE wind-down rung: the inline-judge fallback and git-aware
work-remains. Companion to test_winddown_stop_integration.py (which covers the
already-wired cached-verdict path).

Two new behaviours, both load-bearing:

  1. INLINE JUDGE (lights up the local model live, no daemon). When there is NO
     fresh cached verdict AND the regex floor MISSED the text AND reversible work
     remains, the Stop hook runs the local-LLM judge inline (bounded timeout,
     fail-open) and writes the verdict to winddown_verdict.json. This is exactly
     the slice the cake veiled-stop exposed: regex missed it, no monitor existed.

  2. GIT-AWARE WORK-REMAINS. "Reversible work remains" must include unpushed
     commits / dirty tracked files, not only beads. The cake stop claimed
     "nothing outstanding" with 4 unpushed commits and a drained bead queue.

The oracle that keeps this honest: the judge must NOT run when the regex floor
already caught the offer, nor when no work remains (bounds latency + prevents
nagging a legitimate stop). A spy on the judge proves it.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh


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


# A veiled stop the REGEX FLOOR does NOT match (no wrap/night/push tokens) — the
# case only the model can catch. If winddown_gate's regex ever learns this string,
# this test's premise breaks loudly (assert documents the dependency).
_REGEX_BLIND_OFFER = "Everything's in a good state and there's nothing pressing left to do here."


def test_regex_blind_offer_is_actually_regex_blind():
    # Guard: the whole point of the inline judge is the text regex CANNOT catch.
    import winddown_gate as wg
    assert wg.is_winddown_offer(_REGEX_BLIND_OFFER) is False


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


def test_inline_judge_NOT_called_when_regex_already_caught_it(tmp_path):
    """Fragile-impl reject: the judge must NOT run when regex already flagged
    the offer — that would burn inline latency for no recall gain."""
    calls = []

    def spy_judge(text):
        calls.append(text)
        return True

    tp = _write_transcript(tmp_path, [_asst("want me to wrap for the night, or keep going?")])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=spy_judge,
    )
    assert disp is not None          # still blocks (regex caught it)
    assert calls == []               # but the judge was never consulted


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
    """Model raises → defer to regex floor; a regex-blind offer is NOT fabricated
    into a block. (Fail-open: the gate never depends on the model being up.)"""
    def boom_judge(text):
        raise RuntimeError("model down")

    tp = _write_transcript(tmp_path, [_asst(_REGEX_BLIND_OFFER)])
    disp = sh._winddown_override(
        "conversational", tp, "", tmp_path,
        work_check=_work_remains, judge=boom_judge,
    )
    assert disp is None  # regex didn't catch it + model errored → no block (not fabricated)


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
        work_check=_no_work,  # beads says nothing left
    )
    assert disp is not None  # git work-remains flips it to block
