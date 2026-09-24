#!/usr/bin/env python3
"""Measure a repository's structure — complexity and architecture — from source.

Two modes:

    measure_structure.py tree   <repo> <pkg>
    measure_structure.py series <repo> <pkg> <start> <end> [--step-days N]

`tree` measures the working tree now. `series` checks the repository out at
successive dates and measures every point with this one implementation.

Why the series mode exists
--------------------------
A stored baseline cannot be read as a time series. In the estate that motivated
this tool, a correct fix to a third-party metric library changed the definition
mid-series; reading across that point reported a 39% complexity *rise* as a 14%
*fall*, and reading only after it — a window that began at the series trough —
produced the opposite error. Re-deriving every point from source with one
implementation is the only reading that is not an artifact of where you started.

That is also why this module uses `ast` and nothing else. The counting rules are
visible here rather than inherited from a dependency whose definition can change
underneath a recorded number.

Why architecture is measured alongside complexity
-------------------------------------------------
Complexity per file is not a structural measure on its own. Splitting one large
module into many small ones reduces it whether or not the pieces became
independent. In the motivating repository, per-file complexity fell 44% while a
114-module import cycle — containing the package root itself — went unreported by
every instrument in use, including a complexity baseline, 81 decomposition pins,
architecture tests and four months of gate events. It costs 0.62s on every single
invocation, because a root package inside a cycle means importing any part loads
all of it.

A measurement that reports only size and complexity cannot see that, and reports
the repository as improving throughout.

This tool reports both, and never stores either.

Accuracy
--------
The import graph is validated against a real interpreter, not against its own
rules: its transitive reach equals actual `sys.modules` on the repository it was
built for. That check exists because an earlier version of this file was wrong in
two directions at once — counting deferred function-body imports while dropping
relative imports in `__init__.py` — and the errors partly cancelled, producing a
plausible number and a confidently wrong architectural conclusion.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict

# Sibling modules, imported by path so the tool runs as a script from anywhere.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import structure_payer as _payer  # noqa: E402
import structure_provenance as _prov  # noqa: E402


def _render_provenance(prov: "_prov.Provenance") -> str:
    """Print the recipe beside the number, so a quoted figure carries its source.

    A number copied into a bead or a PR body is a stored measurement with no
    version stamp. That is how a P1 in this repository came to argue from
    figures the tool stopped producing six hours later.
    """
    lines = [
        "",
        f"  measured  {prov.input_repo} @ {prov.input_sha[:10]}",
        f"  tool      {prov.tool_sha[:10]}"
        + ("  DIRTY" if prov.tool_dirty else "")
        + f"  content {prov.tool_content}  config {prov.config_digest}",
        f"  re-derive {prov.recipe}",
    ]
    if prov.warning():
        lines.append(f"  WARNING   {prov.warning()}")
    return "\n".join(lines)

# Nodes that introduce a branch. Held here, and not imported, so that the
# definition of "complexity" in this repository is reviewable in one place.
_BRANCHING = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With,
    ast.AsyncWith, ast.Assert, ast.IfExp, ast.comprehension, ast.BoolOp, ast.Match,
)
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


# ---------------------------------------------------------------- complexity


def file_complexity(source: str) -> tuple[int | None, int]:
    """Return (total cyclomatic complexity, function count) for one module.

    Returns (None, 0) for a module that does not parse, so that a syntactically
    invalid file is reported as unmeasurable rather than silently scored zero.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, 0
    total = functions = 0
    for node in ast.walk(tree):
        if isinstance(node, _FUNC):
            functions += 1
            total += 1  # a function with no branches has complexity 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        elif isinstance(node, _BRANCHING):
            total += 1
    return total, functions


# -------------------------------------------------------------- import graph


def _module_name(relative: pathlib.Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _import_targets(node: ast.AST, package_parts: list[str]) -> list[str]:
    """Candidate module names named by one import statement."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    if node.level:
        # `from . import x` / `from ..pkg import y`
        keep = len(package_parts) - node.level + 1
        base = package_parts[:keep] if node.level > 1 else package_parts
        head = ".".join(base)
        if node.module:
            head = f"{head}.{node.module}" if head else node.module
        return [head] + [f"{head}.{a.name}" for a in node.names if head]
    if node.module:
        return [node.module] + [f"{node.module}.{a.name}" for a in node.names]
    return []


def _deferred_nodes(tree: ast.AST) -> set[int]:
    """ids of import nodes that do not execute when the module is imported.

    Two cases, one rule: an import runs at import time only if control reaches it
    at import time.

    - `if TYPE_CHECKING:` bodies never execute at all.
    - Function and method bodies execute at call time, not import time.

    Both are the standard ways to break an import cycle deliberately. A tool that
    counted them would tell an owner who correctly deferred an import that nothing
    had changed, which is the fastest way to make a measurement ignored.
    """
    deferred: set[int] = set()

    def mark(node: ast.AST) -> None:
        for child in ast.walk(node):
            deferred.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
            mark(node)
        elif isinstance(node, _FUNC):
            mark(node)
    return deferred


def build_import_graph(
    root: pathlib.Path, package: str, *, deferred: bool = False
) -> dict[str, set[str]]:
    """Import edges between modules inside `package`.

    By default returns *import-time* edges: those that execute when the module is
    loaded, and so are the ones that form real runtime cycles and real load cost.
    With `deferred=True`, returns the edges that execute only when a function runs.

    Measured against the repository that motivated this tool, counting deferred
    imports as import-time edges overstated what one module pulls in by 93% — 505
    modules predicted against 262 actually loaded.

    External imports are ignored: this measures the shape of the code under
    review, not its dependency footprint.
    """
    modules: dict[str, pathlib.Path] = {}
    packages: set[str] = set()
    for path in (root / package).rglob("*.py"):
        name = _module_name(path.relative_to(root))
        modules[name] = path
        if path.name == "__init__.py":
            packages.add(name)

    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (SyntaxError, OSError):
            continue
        is_deferred = _deferred_nodes(tree)
        # `from . import x` anchors on the containing package. For a regular
        # module that is its parent; for a package's own __init__ it is the
        # package itself. Using the parent for both silently drops every
        # relative import in every __init__.py -- which is exactly where the
        # convenience re-exports that drive eager loading live.
        parts = name.split(".")
        package_parts = parts if name in packages else parts[:-1]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if (id(node) in is_deferred) != deferred:
                continue
            for target in _import_targets(node, package_parts):
                resolved = target
                if resolved not in modules:
                    # `from pkg.mod import symbol` names the symbol, not a module
                    resolved = target.rsplit(".", 1)[0]
                if resolved not in modules and "." not in target:
                    # Flat script directories put their own directory on sys.path
                    # and import siblings by bare name (`from would_block_stop
                    # import x`). Package-rooted naming never matches those, and
                    # the failure is silent: a tree of 92 interdependent scripts
                    # reports zero edges and therefore a clean architecture.
                    sibling = f"{name.rsplit('.', 1)[0]}.{target}" if "." in name else target
                    if sibling in modules:
                        resolved = sibling
                if resolved not in modules:
                    continue
                # Importing `a.b.c` executes `a`, then `a.b`, then `a.b.c`, so
                # every ancestor package is loaded too. Omitting them understates
                # what one import actually pulls in.
                segments = resolved.split(".")
                for i in range(1, len(segments) + 1):
                    ancestor = ".".join(segments[:i])
                    if ancestor in modules and ancestor != name:
                        graph[name].add(ancestor)
    return graph


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's SCC, iterative. Returns components of size > 1 only.

    A single module importing itself is not expressible in Python; a component of
    one is simply a module, so only genuine cycles are returned.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    components: list[list[str]] = []

    for root_node in graph:
        if root_node in index:
            continue
        work: list[tuple[str, int]] = [(root_node, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recursed = False
            successors = sorted(graph[node])
            for i in range(child_i, len(successors)):
                nxt = successors[i]
                if nxt not in index:
                    work[-1] = (node, i + 1)
                    work.append((nxt, 0))
                    recursed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if recursed:
                continue
            if low[node] == index[node]:
                component = []
                while True:
                    popped = stack.pop()
                    on_stack.discard(popped)
                    component.append(popped)
                    if popped == node:
                        break
                if len(component) > 1:
                    components.append(sorted(component))
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    components.sort(key=len, reverse=True)
    return components


def propagation_cost(graph: dict[str, set[str]]) -> float:
    """Fraction of module pairs (a, b) where a transitively depends on b.

    MacCormack, Rusnak and Baldwin's measure: the share of the system a change
    can reach. Computed over bitsets; the graphs this tool targets are thousands
    of modules at most, where the quadratic closure is cheaper than the machinery
    needed to avoid it.
    """
    nodes = list(graph)
    n = len(nodes)
    if n == 0:
        return 0.0
    position = {name: i for i, name in enumerate(nodes)}
    reach = [0] * n
    for name, i in position.items():
        for target in graph[name]:
            reach[i] |= 1 << position[target]
    changed = True
    while changed:
        changed = False
        for i in range(n):
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
    return sum(bin(r).count("1") for r in reach) / (n * n)


# ------------------------------------------------------------------ results


@dataclass
class Structure:
    """One measurement. Derived on demand; never persisted by this tool."""

    date: str = ""
    commit: str = ""
    files: int = 0
    complexity: int = 0
    functions: int = 0
    worst_file: str = ""
    worst_file_complexity: int = 0
    unparsable: list[str] = field(default_factory=list)
    modules: int = 0
    edges: int = 0
    deferred_edges: int = 0
    propagation_cost: float = 0.0
    cycles: int = 0
    modules_in_cycles: int = 0
    largest_cycle: int = 0
    largest_cycle_members: list[str] = field(default_factory=list)

    @property
    def complexity_per_file(self) -> float:
        return self.complexity / self.files if self.files else 0.0

    @property
    def complexity_per_function(self) -> float:
        return self.complexity / self.functions if self.functions else 0.0

    @property
    def cycle_share(self) -> float:
        return self.modules_in_cycles / self.modules if self.modules else 0.0


def measure_tree(root: str | pathlib.Path, package: str) -> Structure:
    """Measure one working tree."""
    root = pathlib.Path(root)
    result = Structure()
    worst = ("", 0)
    for path in (root / package).rglob("*.py"):
        try:
            source = path.read_text(errors="replace")
        except OSError:
            continue
        complexity, functions = file_complexity(source)
        relative = str(path.relative_to(root))
        if complexity is None:
            result.unparsable.append(relative)
            continue
        result.files += 1
        result.complexity += complexity
        result.functions += functions
        if complexity > worst[1]:
            worst = (relative, complexity)
    result.worst_file, result.worst_file_complexity = worst

    graph = build_import_graph(root, package)
    components = strongly_connected(graph)
    result.modules = len(graph)
    result.edges = sum(len(v) for v in graph.values())
    deferred = build_import_graph(root, package, deferred=True)
    result.deferred_edges = sum(len(v) for v in deferred.values())
    result.propagation_cost = propagation_cost(graph)
    result.cycles = len(components)
    result.modules_in_cycles = sum(len(c) for c in components)
    result.largest_cycle = len(components[0]) if components else 0
    result.largest_cycle_members = components[0] if components else []
    return result


# ----------------------------------------------------------------- history


def _git(repo: str | pathlib.Path, *args: str, timeout: int = 300) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return done.stdout.strip()


def commits_in_range(repo, start: str, end: str, step_days: int = 14) -> list[tuple[str, str]]:
    """One commit per step, deduplicated, as (date, sha)."""
    day = _dt.date.fromisoformat(start)
    last = _dt.date.fromisoformat(end)
    points: list[tuple[str, str]] = []
    seen: set[str] = set()
    while day <= last:
        sha = _git(repo, "rev-list", "-1", f"--before={day.isoformat()}T23:59:59", "HEAD", timeout=60)
        if sha and sha not in seen:
            seen.add(sha)
            points.append((day.isoformat(), sha))
        day += _dt.timedelta(days=step_days)
    return points


def measure_at(repo, package: str, sha: str) -> Structure:
    """Measure one commit in a throwaway detached worktree."""
    with tempfile.TemporaryDirectory(prefix="measure-structure-") as tmp:
        checkout = pathlib.Path(tmp) / "tree"
        _git(repo, "worktree", "add", "--detach", "-f", str(checkout), sha)
        try:
            result = measure_tree(checkout, package)
            result.commit = sha[:10]
            return result
        finally:
            _git(repo, "worktree", "remove", "--force", str(checkout), timeout=120)


def measure_series(repo, package: str, start: str, end: str, step_days: int = 14) -> list[Structure]:
    series = []
    for date, sha in commits_in_range(repo, start, end, step_days):
        result = measure_at(repo, package, sha)
        result.date = date
        series.append(result)
    return series


# ------------------------------------------------------------------ report


def _delta(first: float, last: float) -> str:
    if not first:
        return "     n/a"
    return f"{100 * (last - first) / first:+7.1f}%"


def render(series: list[Structure]) -> str:
    lines = [
        f"{'date':12} {'files':>5} {'cc':>7} {'cc/file':>8} {'cc/fn':>6} "
        f"{'worst':>6} {'mods':>5} {'prop':>6} {'cyc':>4} {'in-cyc':>7} {'max cyc':>8}"
    ]
    for s in series:
        lines.append(
            f"{s.date or s.commit:12} {s.files:5} {s.complexity:7,} "
            f"{s.complexity_per_file:8.1f} {s.complexity_per_function:6.2f} "
            f"{s.worst_file_complexity:6,} {s.modules:5} "
            f"{100 * s.propagation_cost:5.2f}% {s.cycles:4} "
            f"{s.modules_in_cycles:4} ({100 * s.cycle_share:.1f}%) {s.largest_cycle:8}"
        )
    if len(series) > 1:
        a, b = series[0], series[-1]
        lines += ["", f"{a.date or a.commit} -> {b.date or b.commit}"]
        for label, x, y in (
            ("files", a.files, b.files),
            ("total cc", a.complexity, b.complexity),
            ("functions", a.functions, b.functions),
            ("cc per file", a.complexity_per_file, b.complexity_per_file),
            ("cc per function", a.complexity_per_function, b.complexity_per_function),
            ("worst file", a.worst_file_complexity, b.worst_file_complexity),
            ("propagation cost", a.propagation_cost, b.propagation_cost),
            ("modules in cycles", a.modules_in_cycles, b.modules_in_cycles),
            ("largest cycle", a.largest_cycle, b.largest_cycle),
        ):
            lines.append(f"  {label:18} {x:10,.2f} -> {y:<10,.2f} {_delta(x, y)}")
        lines += [
            "",
            "  Complexity falling while cycles grow means decomposition without",
            "  separation: the pieces are smaller but cannot be read, tested or",
            "  reused apart. Read the two together or neither.",
        ]
    if series:
        last = series[-1]
        lines.append(
            f"\n  import-time edges: {last.edges:,}   "
            f"deferred (function-body) edges: {last.deferred_edges:,}"
        )
        lines.append(
            "  Only import-time edges are counted as coupling. Deferred imports do "
            "not\n  execute on import, so they neither load code nor form runtime "
            "cycles."
        )
        if last.worst_file:
            lines.append(f"  worst file: {last.worst_file} ({last.worst_file_complexity} CC)")
        if last.largest_cycle_members:
            lines.append(f"  largest cycle ({last.largest_cycle} modules):")
            lines += [f"    {m}" for m in last.largest_cycle_members]
        if last.unparsable:
            lines.append(f"  unparsable ({len(last.unparsable)}): {', '.join(last.unparsable[:5])}")
    return "\n".join(lines)


def module_complexity(root: str | pathlib.Path, package: str) -> dict[str, int]:
    """Complexity keyed by module name, for joining against the import graph."""
    root = pathlib.Path(root)
    out: dict[str, int] = {}
    for path in (root / package).rglob("*.py"):
        try:
            complexity, _ = file_complexity(path.read_text(errors="replace"))
        except OSError:
            continue
        if complexity is not None:
            out[_module_name(path.relative_to(root))] = complexity
    return out


def _provenance(repo, package: str, sha: str, recipe: str) -> _prov.Provenance:
    return _prov.build(
        repo=repo,
        input_sha=sha,
        config={"package": package, "counts": "import-time edges only"},
        recipe=recipe,
        sources=[pathlib.Path(__file__).resolve(),
                 pathlib.Path(__file__).resolve().parent / "structure_payer.py"],
    )


def compare(repo, package: str, base: str, head: str) -> tuple[Structure, Structure]:
    """Measure two refs with one implementation, in one process.

    Both sides are derived here and now. There is no baseline to read and none
    to write, so a change cannot pass by editing a stored number, and the two
    values cannot have been produced by different versions of this tool.
    """
    base_sha = _git(repo, "rev-parse", base, timeout=60)
    head_sha = _git(repo, "rev-parse", head, timeout=60)
    return (measure_at(repo, package, base_sha), measure_at(repo, package, head_sha))


def render_compare(before: Structure, after: Structure) -> str:
    lines = [f"{before.commit} -> {after.commit}", ""]
    # `files` carries no verdict: growing is what a living repository does, and
    # scoring it rewards deletion for its own sake. It is context for the rest.
    for label, x, y, worse_when_up in (
        ("files", before.files, after.files, None),
        ("total cc", before.complexity, after.complexity, True),
        ("cc per function", before.complexity_per_function, after.complexity_per_function, True),
        ("worst file", before.worst_file_complexity, after.worst_file_complexity, True),
        ("modules in cycles", before.modules_in_cycles, after.modules_in_cycles, True),
        ("largest cycle", before.largest_cycle, after.largest_cycle, True),
    ):
        if worse_when_up is None or x == y:
            arrow = ""
        else:
            arrow = "  worse" if (y > x) == worse_when_up else "  better"
        lines.append(f"  {label:20} {x:10,.2f} -> {y:<10,.2f} {_delta(x, y)}{arrow}")

    # Report the quantity beside its denominator. Propagation cost is a ratio,
    # and a ratio over a growing denominator can fall while the thing it
    # measures grows. Saying only "propagation cost improved" is how a 7x rise
    # in blast radius went unremarked in this estate.
    pairs_before = before.propagation_cost * before.modules ** 2
    pairs_after = after.propagation_cost * after.modules ** 2
    for label, s, pairs in (("before", before, pairs_before), ("after", after, pairs_after)):
        lines.append(
            f"  reach {label:6}         {pairs:10,.0f} pairs over {s.modules:,} modules "
            f"({100 * s.propagation_cost:.2f}%)"
        )
    if pairs_before and (pairs_after > pairs_before) and (
        after.propagation_cost < before.propagation_cost
    ):
        growth = 100 * (pairs_after - pairs_before) / pairs_before
        lines.append(
            f"  NOTE  propagation cost fell, but reachable pairs grew {growth:+.0f}%. "
            "The ratio\n        improved only because the denominator grew faster. "
            "Read the quantity."
        )
    lines += [
        "",
        "  Reported, not enforced. A metric movement is evidence for a human",
        "  decision; only a declared boundary should block.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    sub = parser.add_subparsers(dest="mode", required=True)

    tree = sub.add_parser("tree", help="measure a working tree now")
    tree.add_argument("repo")
    tree.add_argument("package")

    series = sub.add_parser("series", help="measure across a date range")
    series.add_argument("repo")
    series.add_argument("package")
    series.add_argument("start")
    series.add_argument("end")
    series.add_argument("--step-days", type=int, default=14)

    cmp_ = sub.add_parser("compare", help="measure two refs and diff them, storing nothing")
    cmp_.add_argument("repo")
    cmp_.add_argument("package")
    cmp_.add_argument("base")
    cmp_.add_argument("head")

    pay = sub.add_parser("payer", help="join structural exposure to observed payment")
    pay.add_argument("repo")
    pay.add_argument("package")
    pay.add_argument("--since", default="6 months ago")
    pay.add_argument("--top", type=int, default=12)
    pay.add_argument("--fix-pattern", default=_payer.DEFAULT_FIX_PATTERN)

    args = parser.parse_args(argv)
    recipe = "python3 tools/measure_structure.py " + " ".join(sys.argv[1:])

    if args.mode == "payer":
        graph = build_import_graph(pathlib.Path(args.repo), args.package)
        if not graph:
            print(f"no modules found under {args.package}/", file=sys.stderr)
            return 1
        complexity = module_complexity(args.repo, args.package)
        changes, fixes, stats = _payer.change_history(
            args.repo, args.package, args.since, set(graph), args.fix_pattern
        )
        rows = _payer.join(graph, complexity, changes, fixes)
        prov = _provenance(args.repo, args.package,
                           _git(args.repo, "rev-parse", "HEAD", timeout=60), recipe)
        if args.json:
            print(json.dumps({
                "provenance": prov.to_dict(),
                "history": stats,
                "modules": [asdict(r) for r in rows],
            }, indent=2))
        else:
            print(_payer.render(rows, stats, top=args.top))
            print(_render_provenance(prov))
        return 0

    if args.mode == "compare":
        before, after = compare(args.repo, args.package, args.base, args.head)
        prov = _provenance(args.repo, args.package, after.commit, recipe)
        if args.json:
            print(json.dumps({"provenance": prov.to_dict(),
                              "base": asdict(before), "head": asdict(after)}, indent=2))
        else:
            print(render_compare(before, after))
            print(_render_provenance(prov))
        return 0

    if args.mode == "tree":
        results = [measure_tree(args.repo, args.package)]
        sha = _git(args.repo, "rev-parse", "HEAD", timeout=60)
    else:
        results = measure_series(args.repo, args.package, args.start, args.end, args.step_days)
        if not results:
            print("no commits in range", file=sys.stderr)
            return 1
        sha = results[-1].commit

    prov = _provenance(args.repo, args.package, sha, recipe)
    if args.json:
        print(json.dumps({"provenance": prov.to_dict(),
                          "measurements": [asdict(r) for r in results]}, indent=2))
    else:
        print(render(results))
        print(_render_provenance(prov))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
