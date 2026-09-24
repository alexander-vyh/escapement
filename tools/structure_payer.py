#!/usr/bin/env python3
"""Join structural position to observed payment.

A structural measurement is not a health signal until it is multiplied by a
payer and a frequency. This module supplies the second half.

The estate's own evidence for why: a 0.62s import cost in `cake` turned out to
have no payer (daily crons behind container cold starts), while a 0.130s hook
cost mattered far more because a human is blocked on it 500-2000 times per
session. The larger number mattered a hundred times less.

And the join changes conclusions, not just their confidence. Measured on
`cake`: the 114-module tangle holds 34.1% of all change activity but only 19.7%
of fix activity, and commits touching it are *smaller* than commits that do not
(median 3 files against 5). Published work on core/periphery found the opposite
— one studied core held 25.8% of files and ~62% of defect-related activity — so
the refactoring warrant that transfers from that literature does not hold here.
Nothing in a structure-only instrument could have shown that.

Two payers, deliberately kept apart:

  * **exposure** — how much of the system a change to a module can reach. A
    property of the graph, and an upper bound: it counts reachability, not
    traffic.
  * **payment** — what was actually spent on it: how often it changed, and how
    much of that was fixing. A property of history, and a lower bound: it sees
    only what has already happened.

High exposure with high payment is a refactor candidate. High exposure with no
payment is a monitoring candidate, and must not be reported as debt.
"""

from __future__ import annotations

import collections
import dataclasses
import re
import subprocess

# Conservative by default: a commit that says it is a fix. Message matching is
# a weak oracle, so the report always states how many commits matched, letting
# an underpowered signal announce itself rather than be quoted as fact.
DEFAULT_FIX_PATTERN = r"^(fix|bugfix|hotfix)(\(|:|\s)|^revert\b|\bfixes #|\bbug\b"


def transitive_reach(graph: dict[str, set[str]]) -> dict[str, int]:
    """For each node, how many nodes it can transitively reach.

    Bitset closure. The graphs this targets are thousands of nodes at most,
    where the quadratic closure costs less than the machinery to avoid it.
    """
    nodes = list(graph)
    position = {name: i for i, name in enumerate(nodes)}
    reach = [0] * len(nodes)
    for name, i in position.items():
        for target in graph[name]:
            reach[i] |= 1 << position[target]
    changed = True
    while changed:
        changed = False
        for i in range(len(nodes)):
            current = reach[i]
            merged = current
            bits = current
            while bits:
                j = (bits & -bits).bit_length() - 1
                merged |= reach[j]
                bits &= bits - 1
            if merged != current:
                reach[i] = merged
                changed = True
    return {name: bin(reach[position[name]]).count("1") for name in nodes}


def reverse(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {name: set() for name in graph}
    for name, targets in graph.items():
        for target in targets:
            if target in out:
                out[target].add(name)
    return out


@dataclasses.dataclass
class ModulePayer:
    module: str
    complexity: int = 0
    reaches: int = 0        # modules this one can reach — blast radius of a change here
    reached_by: int = 0     # modules that can reach this one — exposure to its churn
    changes: int = 0
    fixes: int = 0

    @property
    def exposure(self) -> int:
        return self.reached_by

    @property
    def score(self) -> int:
        """Exposure multiplied by observed payment.

        Ranking by fixes is tempting and usually wrong here: commit-message
        matching finds so few fix commits that the ordering is noise. Change
        count is the better-powered observation, so the rank uses it and the
        fix column is reported beside it without driving the order.
        """
        return self.reached_by * self.changes


def _module_of(path: str, package: str) -> str | None:
    if not path.startswith(f"{package}/") or not path.endswith(".py"):
        return None
    stem = path[:-3]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def change_history(
    repo: str,
    package: str,
    since: str,
    known: set[str],
    fix_pattern: str = DEFAULT_FIX_PATTERN,
) -> tuple[collections.Counter, collections.Counter, dict]:
    """Per-module change and fix counts, plus the stats needed to judge them."""
    out = subprocess.run(
        ["git", "-C", repo, "log", f"--since={since}",
         "--pretty=format:%x01%s", "--name-only"],
        capture_output=True, text=True, timeout=600, check=False,
    ).stdout
    matcher = re.compile(fix_pattern, re.I)
    changes: collections.Counter = collections.Counter()
    fixes: collections.Counter = collections.Counter()
    commits = fix_commits = touching = 0
    subject: str | None = None
    files: list[str] = []

    def flush() -> None:
        nonlocal commits, fix_commits, touching
        if subject is None:
            return
        commits += 1
        is_fix = bool(matcher.search(subject))
        fix_commits += is_fix
        mods = {m for m in (_module_of(f, package) for f in files) if m and m in known}
        if not mods:
            return
        touching += 1
        for module in mods:
            changes[module] += 1
            if is_fix:
                fixes[module] += 1

    for line in out.split("\n"):
        if line.startswith("\x01"):
            flush()
            subject = line[1:]
            files = []
        elif line.strip():
            files.append(line)
    flush()

    stats = {
        "commits": commits,
        "commits_touching_package": touching,
        "fix_commits": fix_commits,
        "fix_share": (fix_commits / commits) if commits else 0.0,
        "fix_pattern": fix_pattern,
    }
    return changes, fixes, stats


def join(
    graph: dict[str, set[str]],
    complexity: dict[str, int],
    changes: collections.Counter,
    fixes: collections.Counter,
) -> list[ModulePayer]:
    forward = transitive_reach(graph)
    backward = transitive_reach(reverse(graph))
    return [
        ModulePayer(
            module=name,
            complexity=complexity.get(name, 0),
            reaches=forward.get(name, 0),
            reached_by=backward.get(name, 0),
            changes=changes.get(name, 0),
            fixes=fixes.get(name, 0),
        )
        for name in graph
    ]


def quadrants(rows: list[ModulePayer]) -> dict[str, list[ModulePayer]]:
    """Split on medians rather than invented thresholds.

    A fixed cutoff is a stored measurement wearing a policy costume: someone
    picked it from one repository's numbers and it silently stops meaning
    anything in the next. The median is derived from the population being
    reported on, every run.
    """
    if not rows:
        return {"refactor": [], "monitor": [], "churn": [], "quiet": []}
    exposures = sorted(r.exposure for r in rows)
    payments = sorted(r.changes for r in rows)
    mid = len(rows) // 2
    # Inclusive against the median. Import graphs are strongly bimodal — a
    # module is usually either reachable from nearly everything or from almost
    # nothing — so a strict `>` puts the median AT the high value and empties
    # the high bucket entirely. Exposure must also be non-zero to count as
    # exposure at all, and payment must be at least one observed change, so a
    # repository with no history cannot manufacture candidates out of zeroes.
    exposure_cut = max(exposures[mid], 1)
    payment_cut = max(payments[mid], 1)
    buckets: dict[str, list[ModulePayer]] = {
        "refactor": [], "monitor": [], "churn": [], "quiet": [],
    }
    for row in rows:
        high_exposure = row.exposure >= exposure_cut
        high_payment = row.changes >= payment_cut
        if high_exposure and high_payment:
            buckets["refactor"].append(row)
        elif high_exposure:
            buckets["monitor"].append(row)
        elif high_payment:
            buckets["churn"].append(row)
        else:
            buckets["quiet"].append(row)
    for rows_ in buckets.values():
        rows_.sort(key=lambda r: (r.score, r.fixes), reverse=True)
    return buckets


def render(rows: list[ModulePayer], stats: dict, top: int = 12) -> str:
    buckets = quadrants(rows)
    total_changes = sum(r.changes for r in rows) or 1
    total_fixes = sum(r.fixes for r in rows) or 1
    lines = [
        f"{len(rows)} modules   "
        f"{stats['commits_touching_package']:,} of {stats['commits']:,} commits touch them",
        "",
        f"{'quadrant':10} {'modules':>8} {'% changes':>10} {'% fixes':>9}   meaning",
    ]
    meaning = {
        "refactor": "high exposure AND paid for — the only refactor warrant",
        "monitor": "high exposure, nobody paying — watch, do not refactor",
        "churn": "paid for but contained — cost is real and local",
        "quiet": "neither — leave alone",
    }
    for name in ("refactor", "monitor", "churn", "quiet"):
        rows_ = buckets[name]
        changes = sum(r.changes for r in rows_)
        fixes = sum(r.fixes for r in rows_)
        lines.append(
            f"{name:10} {len(rows_):8} {100 * changes / total_changes:9.1f}% "
            f"{100 * fixes / total_fixes:8.1f}%   {meaning[name]}"
        )

    lines += ["", f"refactor candidates, by exposure x changes (top {top}):", ""]
    head = buckets["refactor"][:top]
    if not head:
        lines.append("  none — no module is both highly exposed and actively paid for.")
    else:
        lines.append(
            f"  {'reached_by':>10} {'changes':>8} {'fixes':>6} {'cc':>6} {'score':>9}  module"
        )
        for row in head:
            lines.append(
                f"  {row.reached_by:10} {row.changes:8} {row.fixes:6} "
                f"{row.complexity:6} {row.score:9,}  {row.module}"
            )

    # State the power of the defect oracle rather than letting a weak signal be
    # quoted as fact. Commit-message matching is a poor proxy, and a reader can
    # only discount it if the match rate is visible.
    lines += [
        "",
        f"  defect oracle: {stats['fix_commits']:,} of {stats['commits']:,} commits "
        f"matched ({100 * stats['fix_share']:.1f}%), pattern {stats['fix_pattern']!r}",
    ]
    if stats["fix_commits"] < 50:
        lines.append(
            "  UNDERPOWERED: too few matched commits to rank by fixes. Treat the "
            "fix column\n  as indicative only, and prefer linked defect records "
            "where they exist."
        )
    lines += [
        "",
        "  Exposure is an upper bound: it counts what a change COULD reach, not",
        "  what traffic exists. Payment is a lower bound: it sees only what has",
        "  already been spent. Neither is a verdict; together they say whether",
        "  a structural finding has anyone behind it.",
    ]
    return "\n".join(lines)
