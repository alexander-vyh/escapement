#!/usr/bin/env python3
"""Attribute post-landing repair back to the change that caused it.

The reward signal coding models are trained on cannot see maintenance cost: the
episode ends when the tests pass, and the bill arrives months later, across a gap no
credit assignment crosses. That gap is unbridgeable for a benchmark. It is not
unbridgeable here — this repository *is* the episode, and its whole timeline is on
disk. So the missing signal can be measured instead of learned.

For each source file this computes how often it is repaired, and how often that repair
lands within a week of the change it repairs. For each landing commit it computes how
many repairs it induced. The output is measurement only: no gate derives from it until
recurrence is observed (claude/rules/gate-design.md — gate what repeats, not what could).

Repair intent is read from the commit subject. That is coarse, and the report says so
by carrying the classifier with it; the ranking it produces is checked against known
ground truth in `--self-test` rather than assumed correct.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "claude" / "hooks"))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover - signal capture is never load-bearing
    def _record_signal(*_args, **_kwargs) -> bool:
        return False

REPAIR_SUBJECT = re.compile(
    r"\b(fix|fixes|fixed|bug|revert|reverts|regression|broken|repair|corrects?|hotfix)\b",
    re.IGNORECASE,
)

SOURCE_SUFFIXES = (".py", ".ts", ".js", ".sh")
EXCLUDED_PARTS = ("/vendor/", "/node_modules/", "/generated/", "/testdata/",
                  "/fixtures/", "/.beads/", "/dist/", "/build/")
DAY = 86400


def is_source(path: str) -> bool:
    if not path.endswith(SOURCE_SUFFIXES):
        return False
    return not any(part in f"/{path}" for part in EXCLUDED_PARTS)


@dataclass
class Commit:
    sha: str
    ts: int
    subject: str
    files: list[str]

    @property
    def is_repair(self) -> bool:
        return bool(REPAIR_SUBJECT.search(self.subject))


@dataclass
class FileRecord:
    path: str
    touches: int = 0
    repairs: int = 0
    repairs_within_7d: int = 0
    inducing_commits: list[str] = field(default_factory=list)

    @property
    def repair_rate(self) -> float:
        return self.repairs / self.touches if self.touches else 0.0

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "touches": self.touches,
            "repairs": self.repairs,
            "repairs_within_7d": self.repairs_within_7d,
            "repair_rate": round(self.repair_rate, 3),
            "inducing_commits": self.inducing_commits,
        }


def read_history(repo: Path, limit: int | None = None) -> list[Commit]:
    args = ["git", "log", "--no-merges", "--name-only", "--format=%x01%H%x02%ct%x02%s"]
    if limit:
        args.append(f"-{limit}")
    out = subprocess.run(args, cwd=str(repo), capture_output=True, text=True,
                         timeout=180).stdout
    commits: list[Commit] = []
    for block in out.split("\x01"):
        if not block.strip():
            continue
        header, *rest = block.split("\n")
        sha, ts, subject = header.split("\x02", 2)
        files = [line for line in rest if line.strip()]
        commits.append(Commit(sha, int(ts), subject, files))
    commits.sort(key=lambda c: c.ts)
    return commits


def analyze(commits: list[Commit], window_days: int = 7) -> dict:
    """Attribute each repair to the landing that last touched the repaired file."""
    window = window_days * DAY
    files: dict[str, FileRecord] = {}
    last_change: dict[str, Commit] = {}
    induced: dict[str, int] = defaultdict(int)
    induced_files: dict[str, set] = defaultdict(set)

    for commit in commits:
        for path in commit.files:
            if not is_source(path):
                continue
            record = files.setdefault(path, FileRecord(path))
            record.touches += 1

            if commit.is_repair:
                previous = last_change.get(path)
                # A repair commit that also *introduces* the file has nothing to
                # blame: the file has no prior landing.
                if previous is not None:
                    record.repairs += 1
                    if commit.ts - previous.ts <= window:
                        record.repairs_within_7d += 1
                        record.inducing_commits.append(previous.sha[:12])
                        induced[previous.sha] += 1
                        induced_files[previous.sha].add(path)
            last_change[path] = commit

    graded = [f for f in files.values() if f.touches >= 2]
    sinks = sorted(graded, key=lambda f: (-f.repairs_within_7d, -f.repairs, f.path))
    landings = sorted(induced.items(), key=lambda kv: -kv[1])

    by_sha = {c.sha: c for c in commits}
    total_touches = sum(f.touches for f in files.values())
    total_within = sum(f.repairs_within_7d for f in files.values())

    return {
        "commits": len(commits),
        "source_files": len(files),
        "total_source_touches": total_touches,
        "repairs_within_7d": total_within,
        "repair_within_7d_share": round(total_within / total_touches, 3) if total_touches else 0.0,
        "window_days": window_days,
        "repair_sinks": [f.as_dict() for f in sinks if f.repairs_within_7d or f.repairs],
        "inducing_landings": [
            {
                "sha": sha[:12],
                "subject": by_sha[sha].subject,
                "induced_repairs": count,
                "files": sorted(induced_files[sha]),
            }
            for sha, count in landings
        ],
    }


def emit_signal(report: dict) -> None:
    for sink in report["repair_sinks"][:20]:
        _record_signal(
            "repair_attribution",
            decision="signal",
            reason=f"{sink['path']} repaired within 7d {sink['repairs_within_7d']}x",
            path=sink["path"],
            touches=sink["touches"],
            repairs=sink["repairs"],
            repairs_within_7d=sink["repairs_within_7d"],
            inducing_commits=sink["inducing_commits"],
        )


def render(report: dict) -> str:
    lines = [
        f"commits: {report['commits']}   source files: {report['source_files']}",
        f"repairs within {report['window_days']}d: {report['repairs_within_7d']} "
        f"({report['repair_within_7d_share']:.0%} of source touches)",
        "",
        "top repair sinks:",
        f"  {'within7d':>8} {'repairs':>8} {'touches':>8}  path",
    ]
    for sink in report["repair_sinks"][:15]:
        lines.append(
            f"  {sink['repairs_within_7d']:8} {sink['repairs']:8} {sink['touches']:8}  {sink['path']}"
        )
    lines += ["", "landings that induced the most repair:"]
    for landing in report["inducing_landings"][:10]:
        lines.append(f"  {landing['induced_repairs']:3}  {landing['sha']}  {landing['subject'][:70]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test: behavioral controls against a synthetic history with known truth
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str, ts: int | None = None) -> None:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if ts is not None:
        stamp = f"{ts} +0000"
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    subprocess.run(["git", *args], cwd=str(repo), env=env, check=True,
                   capture_output=True, text=True)


def _commit(repo: Path, path: str, body: str, subject: str, ts: int) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    _git(repo, "add", path, ts=ts)
    _git(repo, "commit", "-m", subject, ts=ts)


def self_test() -> int:
    """Behavioral controls. Each kills a specific fragile implementation.

    positive  — a file repaired 2h after its landing is ranked, and the landing is blamed
    negative1 — a file that is touched repeatedly but never repaired is NOT ranked
    negative2 — a repair 40 days after the landing counts as a repair but NOT within 7d
                (kills an implementation that ignores the time window)
    negative3 — a repair commit that also creates the file blames nothing
                (kills an implementation that attributes to itself or to a null landing)
    """
    base = 1_700_000_000
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repair-attr-selftest-") as tmp:
        repo = Path(tmp)
        _git(repo, "init", "-q", "-b", "main")

        _commit(repo, "a.py", "def a(): return 1\n", "add a", base)
        _commit(repo, "a.py", "def a(): return 2\n", "fix: a crashes on empty input",
                base + 2 * 3600)

        _commit(repo, "b.py", "def b(): return 1\n", "add b", base)
        _commit(repo, "b.py", "def b(): return 2\n", "extend b", base + DAY)
        _commit(repo, "b.py", "def b(): return 3\n", "extend b again", base + 2 * DAY)

        _commit(repo, "c.py", "def c(): return 1\n", "add c", base)
        _commit(repo, "c.py", "def c(): return 2\n", "fix: long-dormant c regression",
                base + 40 * DAY)

        _commit(repo, "d.py", "def d(): return 1\n", "fix: add missing d guard",
                base + 3 * DAY)

        report = analyze(read_history(repo))
        ranked = {s["path"]: s for s in report["repair_sinks"]}

        if "a.py" not in ranked or ranked["a.py"]["repairs_within_7d"] != 1:
            failures.append("positive: a.py repaired 2h after landing was not ranked within 7d")
        elif not ranked["a.py"]["inducing_commits"]:
            failures.append("positive: a.py repair was not attributed to its landing commit")

        if "b.py" in ranked:
            failures.append("negative1: b.py was never repaired but appears in the ranking")

        if "c.py" not in ranked:
            failures.append("negative2: c.py repair after 40d was dropped entirely")
        elif ranked["c.py"]["repairs"] != 1 or ranked["c.py"]["repairs_within_7d"] != 0:
            failures.append(
                "negative2: c.py repair after 40d was counted inside the 7d window "
                "(the time window is being ignored)"
            )

        if "d.py" in ranked:
            failures.append(
                "negative3: d.py was created by its own repair commit and has no prior "
                "landing, but was still attributed"
            )

        induced = {landing["sha"] for landing in report["inducing_landings"]}
        if len(induced) != 1:
            failures.append(
                f"exactly one landing should be blamed in this history, got {len(induced)}"
            )

    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print("self-test passed: 1 positive + 3 negative controls")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--signal", action="store_true",
                        help="append findings to the gate-signal store")
    parser.add_argument("--self-test", action="store_true",
                        help="run behavioral controls and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    repo = Path(args.repo).resolve()
    report = analyze(read_history(repo, args.limit), args.window_days)
    if args.signal:
        emit_signal(report)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
