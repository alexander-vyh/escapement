#!/usr/bin/env python3
"""Executed negative control: did any changed test actually fail before the fix?

Every oracle gate in this repository sits downstream of tests that have never been
proven non-vacuous. `tdd-gate.py` checks only that test files were *touched* first;
`oracle_strength_diff.py` dropped its blocking tier; the molecule formulas ask for a
failing test in prose. Nothing has ever executed the question.

This module executes it. For a change, it reverts the PRODUCTION hunks while keeping
the changed tests, then runs those tests. A test that still passes did not detect the
change, so it is not evidence about it.

Why revert hunks rather than check out the parent commit: the parent does not contain
the new test files, so the tests could not run there at all. Reverting only production
files keeps the new tests present and asks the precise question.

Verdicts (per change):
  detecting-failure  — a changed test failed without the production change. Real oracle.
  detecting-error    — a changed test errored (e.g. the symbol under test does not exist
                       yet). Also detection: the test is coupled to the change.
  vacuous            — every changed test passed without the production change.
  no-test            — production files changed, no test file changed.
  not-applicable     — no production files changed (docs, generated surfaces, test-only).

`--replay` answers the question the walking skeleton exists for: across this
repository's history, how often is a landing vacuous, and does that overlap with the
commits that had to be repaired within 24 hours?
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# A commit whose subject matches this is treated as repair work. Coarse by
# construction: it classifies intent from the subject line only, and the replay
# reports the overlap it produces rather than asserting the label is exact.
REPAIR_SUBJECT = re.compile(
    r"\b(fix|fixes|fixed|bug|revert|reverts|regression|broken|repair|corrects?|hotfix)\b",
    re.IGNORECASE,
)

TEST_DIR_PARTS = ("tests/", "/tests/", "test/", "/test/")
# Measured single-commit cost on this repository is 1.4-11s. The ceiling exists for
# the rare commit whose changed tests spawn heavy subprocess suites; those are
# reported as `skipped` rather than allowed to wall the replay or a landing.
PYTEST_TIMEOUT_SECONDS = 90


def _run(args: list[str], cwd: Path, timeout: int = 60, env: dict | None = None):
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env
    )


def is_test_file(path: str) -> bool:
    """True for files whose purpose is testing, in this repo's conventions."""
    name = Path(path).name
    if name == "conftest.py":
        return True
    if not path.endswith(".py"):
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in path for part in TEST_DIR_PARTS)


def is_production_python(path: str) -> bool:
    return path.endswith(".py") and not is_test_file(path)


@dataclass
class Verdict:
    sha: str
    subject: str
    verdict: str
    tests: list[str] = field(default_factory=list)
    production: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "sha": self.sha,
            "subject": self.subject,
            "verdict": self.verdict,
            "tests": self.tests,
            "production": self.production,
            "detail": self.detail,
        }


def changed_files(repo: Path, sha: str) -> list[str]:
    out = _run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", sha], repo
    )
    return sorted({line for line in out.stdout.splitlines() if line.strip()})


def _sandbox_env(home: Path) -> dict:
    """pytest runs with HOME redirected so replaying history cannot write into the
    real home directory (several gates in this repo read ~/.claude)."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def evaluate_change(
    repo: Path,
    scratch: Path,
    head: str,
    base: str,
    files: list[str],
    label: str,
    home: Path,
) -> Verdict:
    """Check out `head` in `scratch`, restore its production files to `base`, and run
    the tests the change touched.

    This is the whole mechanism. `head` may be one commit or a branch tip; `base` its
    parent or the merge-base with the landing branch. Only production files are
    restored, so the tests under examination remain at their `head` content — asking
    the parent commit directly would not work, because the new tests do not exist there.
    """
    tests = [f for f in files if is_test_file(f)]
    production = [f for f in files if is_production_python(f)]

    if not production:
        return Verdict(head, label, "not-applicable", tests, production,
                       "no production python changed")
    if not tests:
        return Verdict(head, label, "no-test", tests, production,
                       "production changed with no test change")

    checkout = _run(["git", "checkout", "--force", "--detach", head], scratch, timeout=120)
    if checkout.returncode != 0:
        return Verdict(head, label, "skipped", tests, production,
                       f"checkout failed: {checkout.stderr.strip()[:200]}")
    _run(["git", "clean", "-qfdx", "--exclude=.venv"], scratch, timeout=120)

    # Revert production hunks only. Files the change added do not exist at the base,
    # so they are removed rather than restored.
    for path in production:
        exists = _run(["git", "cat-file", "-e", f"{base}:{path}"], scratch)
        if exists.returncode == 0:
            _run(["git", "checkout", base, "--", path], scratch)
        else:
            (scratch / path).unlink(missing_ok=True)

    present = [t for t in tests if (scratch / t).is_file() and Path(t).name != "conftest.py"]
    if not present:
        return Verdict(head, label, "not-applicable", tests, production,
                       "changed tests are not runnable files (conftest/deleted)")

    try:
        result = _run(
            # -x: the verdict only needs to know whether ANY changed test detected the
            # change, so stop at the first failure. The all-pass (vacuous) case still
            # runs everything, which is correct -- that verdict requires exhaustion.
            [sys.executable, "-m", "pytest", *present, "-q", "-x", "-p", "no:cacheprovider"],
            scratch,
            timeout=PYTEST_TIMEOUT_SECONDS,
            env=_sandbox_env(home),
        )
    except subprocess.TimeoutExpired:
        return Verdict(head, label, "skipped", tests, production, "pytest timed out")

    tail = (result.stdout or result.stderr).strip().splitlines()
    detail = tail[-1][:200] if tail else ""

    # pytest exit codes: 0 all passed, 1 tests failed, 2 interrupted,
    # 3 internal error, 4 usage error, 5 no tests collected. Under `-x`, a collection
    # error also exits 1, so the failure/error split is read from the summary line
    # rather than the exit code alone -- otherwise a verdict of "failure" is printed
    # beside a detail line reading "1 error", which is the report lying quietly.
    if result.returncode == 0:
        return Verdict(head, label, "vacuous", tests, production, detail)
    if result.returncode == 5:
        return Verdict(head, label, "not-applicable", tests, production,
                       "no tests collected")
    errored = "error" in detail.lower() and "failed" not in detail.lower()
    kind = "detecting-error" if errored else "detecting-failure"
    return Verdict(head, label, kind, tests, production, detail)


def evaluate_commit(repo: Path, scratch: Path, sha: str, subject: str, home: Path) -> Verdict:
    """Evaluate a single commit against its own parent."""
    parent = _run(["git", "rev-parse", f"{sha}^"], repo).stdout.strip()
    if not parent:
        return Verdict(sha, subject, "skipped", [], [], "no parent commit")
    return evaluate_change(repo, scratch, sha, parent, changed_files(repo, sha), subject, home)


def range_files(repo: Path, base: str, head: str) -> list[str]:
    out = _run(["git", "diff", "--name-only", f"{base}...{head}"], repo, timeout=120)
    return sorted({line for line in out.stdout.splitlines() if line.strip()})


def evaluate_range(repo: Path, base: str, head: str = "HEAD") -> Verdict:
    """Evaluate a whole branch against its merge-base. Used by the landing gate.

    Creates and removes its own scratch worktree so callers (hooks) do not manage one.
    """
    parent_dir = Path(tempfile.mkdtemp(prefix="prepatch-range-"))
    scratch = parent_dir / "wt"
    home = parent_dir / "home"
    home.mkdir()
    add = _run(["git", "worktree", "add", "--detach", str(scratch), head], repo, timeout=180)
    if add.returncode != 0:
        shutil.rmtree(parent_dir, ignore_errors=True)
        return Verdict(head, "range", "skipped", [], [],
                       f"scratch worktree failed: {add.stderr.strip()[:200]}")
    try:
        files = range_files(repo, base, head)
        return evaluate_change(repo, scratch, head, base, files, f"{base[:12]}..{head}", home)
    finally:
        _run(["git", "worktree", "remove", "--force", str(scratch)], repo, timeout=120)
        shutil.rmtree(parent_dir, ignore_errors=True)


def history(repo: Path, limit: int | None) -> list[tuple[str, int, str]]:
    args = ["git", "log", "--no-merges", "--format=%H\x02%ct\x02%s"]
    if limit:
        args.append(f"-{limit}")
    out = _run(args, repo, timeout=120).stdout
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, ts, subject = line.split("\x02", 2)
        rows.append((sha, int(ts), subject))
    return list(reversed(rows))


def repaired_within(repo: Path, rows: list[tuple[str, int, str]], hours: int) -> set[str]:
    """Commits followed, inside `hours`, by a repair commit touching a shared file."""
    touched = {sha: set(changed_files(repo, sha)) for sha, _, _ in rows}
    window = hours * 3600
    repaired: set[str] = set()
    for index, (sha, ts, _) in enumerate(rows):
        for later_sha, later_ts, later_subject in rows[index + 1:]:
            if later_ts - ts > window:
                break
            if not REPAIR_SUBJECT.search(later_subject):
                continue
            if touched[sha] & touched[later_sha]:
                repaired.add(sha)
                break
    return repaired


def replay(repo: Path, limit: int | None, progress: bool) -> dict:
    rows = history(repo, limit)
    repaired = repaired_within(repo, rows, 24)

    scratch_parent = Path(tempfile.mkdtemp(prefix="prepatch-replay-"))
    scratch = scratch_parent / "wt"
    home = scratch_parent / "home"
    home.mkdir()
    add = _run(["git", "worktree", "add", "--detach", str(scratch), "HEAD"], repo, timeout=180)
    if add.returncode != 0:
        raise SystemExit(f"could not create scratch worktree: {add.stderr}")

    verdicts: list[Verdict] = []
    try:
        for index, (sha, _, subject) in enumerate(rows, 1):
            verdicts.append(evaluate_commit(repo, scratch, sha, subject, home))
            if progress and index % 10 == 0:
                print(f"  ... {index}/{len(rows)}", file=sys.stderr)
    finally:
        _run(["git", "worktree", "remove", "--force", str(scratch)], repo, timeout=120)
        shutil.rmtree(scratch_parent, ignore_errors=True)

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1

    graded = [v for v in verdicts if v.verdict in {"vacuous", "detecting-failure",
                                                   "detecting-error", "no-test"}]
    weak = {v.sha for v in graded if v.verdict in {"vacuous", "no-test"}}
    strong = {v.sha for v in graded if v.verdict.startswith("detecting")}
    graded_shas = weak | strong

    overlap = {
        "vacuous_and_repaired_24h": len(weak & repaired),
        "vacuous_not_repaired_24h": len(weak - repaired),
        "detecting_and_repaired_24h": len(strong & repaired),
        "detecting_not_repaired_24h": len(strong - repaired),
    }
    weak_repair_rate = (len(weak & repaired) / len(weak)) if weak else None
    strong_repair_rate = (len(strong & repaired) / len(strong)) if strong else None

    return {
        "repo": str(repo),
        "commits": len(rows),
        "classified": len(verdicts),
        "counts": counts,
        "graded": len(graded_shas),
        "repaired_within_24h": len(repaired),
        "overlap": overlap,
        "repair_rate_when_oracle_weak": weak_repair_rate,
        "repair_rate_when_oracle_detects": strong_repair_rate,
        "verdicts": [v.as_dict() for v in verdicts],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository to inspect")
    parser.add_argument("--replay", action="store_true", help="replay across history")
    parser.add_argument("--commit", help="evaluate a single commit")
    parser.add_argument("--limit", type=int, help="most recent N commits")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--progress", action="store_true", help="progress to stderr")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()

    if args.commit:
        subject = _run(["git", "log", "-1", "--format=%s", args.commit], repo).stdout.strip()
        parent_dir = Path(tempfile.mkdtemp(prefix="prepatch-one-"))
        scratch = parent_dir / "wt"
        home = parent_dir / "home"
        home.mkdir()
        _run(["git", "worktree", "add", "--detach", str(scratch), "HEAD"], repo, timeout=180)
        try:
            verdict = evaluate_commit(repo, scratch, args.commit, subject, home)
        finally:
            _run(["git", "worktree", "remove", "--force", str(scratch)], repo, timeout=120)
            shutil.rmtree(parent_dir, ignore_errors=True)
        print(json.dumps(verdict.as_dict(), indent=2) if args.json
              else f"{verdict.verdict}: {verdict.detail}")
        return 0

    if not args.replay:
        parser.error("one of --replay or --commit is required")

    report = replay(repo, args.limit, args.progress)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"commits classified: {report['classified']}")
    for verdict, count in sorted(report["counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:20} {count:4}")
    print(f"\nrepaired within 24h: {report['repaired_within_24h']}")
    weak = report["repair_rate_when_oracle_weak"]
    strong = report["repair_rate_when_oracle_detects"]
    print(f"repair rate when the oracle was weak (vacuous or no test): "
          f"{'n/a' if weak is None else f'{weak:.0%}'}")
    print(f"repair rate when a changed test detected the change:       "
          f"{'n/a' if strong is None else f'{strong:.0%}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
