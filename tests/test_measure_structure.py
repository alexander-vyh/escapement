"""Behavioural tests for tools/measure_structure.py.

Each test builds a tree whose correct answer is known by construction and would
be reported wrongly by a specific plausible implementation mistake. The mistakes
guarded against are the ones that actually occurred while developing this tool:
counting TYPE_CHECKING imports as runtime edges, treating `from pkg.mod import
symbol` as an import of `pkg.mod.symbol`, scoring an unparsable file as zero, and
reporting a decomposition as an improvement while it introduces a cycle.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.measure_structure import (  # noqa: E402
    build_import_graph,
    file_complexity,
    measure_series,
    measure_tree,
    propagation_cost,
    strongly_connected,
)


def write(root: pathlib.Path, relative: str, source: str) -> pathlib.Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


# --------------------------------------------------------------- complexity


def test_straight_line_function_has_complexity_one():
    """A function with no branches is 1, not 0: the count is paths, not branches."""
    complexity, functions = file_complexity("def f():\n    return 1\n")
    assert (complexity, functions) == (1, 1)


def test_each_branch_adds_one():
    source = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    for i in range(3):\n"
        "        pass\n"
        "    while x:\n"
        "        break\n"
        "    return 0\n"
    )
    complexity, _ = file_complexity(source)
    assert complexity == 4  # 1 base + if + for + while


def test_boolean_operator_counts_each_extra_operand():
    """`a and b and c` is two extra paths, not one.

    Counting a BoolOp as a single branch understates compound conditions, which
    are exactly the conditions worth flagging.
    """
    one, _ = file_complexity("def f(a, b):\n    return a and b\n")
    two, _ = file_complexity("def f(a, b, c):\n    return a and b and c\n")
    assert (one, two) == (2, 3)


def test_unparsable_file_is_reported_not_scored_zero(tmp_path):
    """A syntax error must not read as a perfectly simple file."""
    complexity, _ = file_complexity("def broken(:\n")
    assert complexity is None

    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/good.py", "def f():\n    if 1:\n        pass\n")
    write(tmp_path, "pkg/bad.py", "def broken(:\n")
    result = measure_tree(tmp_path, "pkg")

    assert result.unparsable == ["pkg/bad.py"]
    assert result.files == 2  # __init__ and good, not bad
    assert result.worst_file == "pkg/good.py"


# -------------------------------------------------------------- import graph


def test_symbol_import_resolves_to_its_module(tmp_path):
    """`from pkg.mod import name` is an edge to pkg.mod, and to pkg.

    Resolving it to the non-existent module `pkg.mod.name` drops the edge and
    silently reports a system as less connected than it is. The package edge is
    there because importing `pkg.mod` executes `pkg/__init__.py` first.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/mod.py", "VALUE = 1\n")
    write(tmp_path, "pkg/user.py", "from pkg.mod import VALUE\n")
    graph = build_import_graph(tmp_path, "pkg")
    assert graph["pkg.user"] == {"pkg", "pkg.mod"}


def test_relative_import_resolves(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/sub/__init__.py", "")
    write(tmp_path, "pkg/sub/a.py", "VALUE = 1\n")
    write(tmp_path, "pkg/sub/b.py", "from . import a\n")
    graph = build_import_graph(tmp_path, "pkg")
    assert "pkg.sub.a" in graph["pkg.sub.b"]


def test_external_imports_are_not_edges(tmp_path):
    """Third-party dependencies are not part of this system's shape."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/a.py", "import json\nimport os.path\nfrom collections import defaultdict\n")
    graph = build_import_graph(tmp_path, "pkg")
    assert graph["pkg.a"] == set()


def test_type_checking_import_is_not_a_runtime_cycle(tmp_path):
    """The canonical fix for a cycle must register as a fix.

    Guarding an import with TYPE_CHECKING is how a real cycle gets broken while
    keeping annotations. A tool that still reports a cycle afterwards tells the
    owner their correct fix did nothing.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/a.py", "from pkg import b\n")
    write(
        tmp_path,
        "pkg/b.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pkg import a\n",
    )
    result = measure_tree(tmp_path, "pkg")
    assert result.cycles == 0
    assert result.largest_cycle == 0


def test_runtime_back_import_is_a_cycle(tmp_path):
    """The same shape without the guard is a genuine cycle."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/a.py", "from pkg import b\n")
    write(tmp_path, "pkg/b.py", "from pkg import a\n")
    result = measure_tree(tmp_path, "pkg")
    assert result.cycles == 1
    assert result.largest_cycle == 2
    assert result.largest_cycle_members == ["pkg.a", "pkg.b"]


def test_function_body_import_is_not_an_import_time_edge(tmp_path):
    """Deferring an import into a function is a real fix and must register as one.

    Python executes a function-body import at call time, so it neither loads the
    target on import nor forms a runtime cycle. Counting it would tell an owner who
    correctly broke a cycle that nothing changed — the same error the TYPE_CHECKING
    guard already avoids. Against the motivating repository, counting deferred
    imports overstated what one module pulls in by 93%.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/heavy.py", "VALUE = 1\n")
    write(
        tmp_path,
        "pkg/user.py",
        "def run():\n    from pkg import heavy\n    return heavy.VALUE\n",
    )
    assert build_import_graph(tmp_path, "pkg")["pkg.user"] == set()
    assert build_import_graph(tmp_path, "pkg", deferred=True)["pkg.user"] == {"pkg", "pkg.heavy"}

    result = measure_tree(tmp_path, "pkg")
    assert result.edges == 0
    assert result.deferred_edges == 2


def test_moving_an_import_into_a_function_breaks_the_cycle(tmp_path):
    """The canonical cycle fix, measured end to end."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/a.py", "from pkg import b\n")
    write(tmp_path, "pkg/b.py", "from pkg import a\n")
    assert measure_tree(tmp_path, "pkg").largest_cycle == 2

    write(tmp_path, "pkg/b.py", "def go():\n    from pkg import a\n    return a\n")
    fixed = measure_tree(tmp_path, "pkg")
    assert fixed.cycles == 0
    assert fixed.deferred_edges == 2  # the coupling is still reported, just not as import-time


def test_method_body_import_is_also_deferred(tmp_path):
    """A method is a function: the rule must not be defeated by a class wrapper."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/heavy.py", "VALUE = 1\n")
    write(
        tmp_path,
        "pkg/user.py",
        "class C:\n    def run(self):\n        from pkg import heavy\n        return heavy\n",
    )
    assert build_import_graph(tmp_path, "pkg")["pkg.user"] == set()


def test_module_level_import_inside_a_try_is_still_import_time(tmp_path):
    """An optional-dependency guard still executes on import.

    Only functions and TYPE_CHECKING defer. Treating any nested import as deferred
    would silently drop real edges.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/heavy.py", "VALUE = 1\n")
    write(
        tmp_path,
        "pkg/user.py",
        "try:\n    from pkg import heavy\nexcept ImportError:\n    heavy = None\n",
    )
    assert "pkg.heavy" in build_import_graph(tmp_path, "pkg")["pkg.user"]


def test_predicted_load_matches_what_python_actually_imports(tmp_path):
    """The graph's transitive reach must equal real sys.modules, not approximate it.

    This is the property that makes propagation cost meaningful. Two bugs broke it
    in opposite directions and cancelled each other's symptoms: function-body
    imports were counted (overstating), while relative imports in `__init__.py`
    and implicitly-loaded ancestor packages were dropped (understating). Verified
    here against a real interpreter rather than against the graph's own rules.
    """
    write(tmp_path, "pkg/__init__.py", "from .core import engine\n")
    write(tmp_path, "pkg/core/__init__.py", "")
    write(tmp_path, "pkg/core/engine.py", "from pkg.util import helper\n")
    write(tmp_path, "pkg/util/__init__.py", "")
    write(tmp_path, "pkg/util/helper.py", "VALUE = 1\n")
    write(tmp_path, "pkg/lazy.py", "def go():\n    from pkg.util import helper\n    return helper\n")

    graph = build_import_graph(tmp_path, "pkg")
    reached = {"pkg"}
    stack = ["pkg"]
    while stack:
        for target in graph.get(stack.pop(), ()):
            if target not in reached:
                reached.add(target)
                stack.append(target)

    actual = subprocess.run(
        [sys.executable, "-c",
         "import sys, pkg; print(len([m for m in sys.modules if m == 'pkg' or m.startswith('pkg.')]))"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert len(reached) == int(actual.stdout.strip())
    assert "pkg.lazy" not in reached  # deferred, and never imported by anything


def test_flat_script_directory_siblings_are_edges(tmp_path):
    """Scripts that sys.path their own directory import siblings by bare name.

    This is escapement's own primary Python style: `from would_block_stop import x`
    rather than `from harness.bin.would_block_stop import x`. Package-rooted naming
    never matches those, and the failure mode is silent rather than loud — 92
    interdependent scripts reported zero edges and therefore a flawless
    architecture, which is worse than an error because it looks like good news.
    """
    write(tmp_path, "bin/helper.py", "VALUE = 1\n")
    write(tmp_path, "bin/main.py", "import sys\nsys.path.insert(0, '.')\nfrom helper import VALUE\n")
    graph = build_import_graph(tmp_path, "bin")
    assert graph["bin.main"] == {"bin.helper"}


def test_bare_import_without_a_sibling_is_not_an_edge(tmp_path):
    """Sibling resolution must not invent edges for stdlib or third-party names."""
    write(tmp_path, "bin/main.py", "import json\nimport requests\n")
    assert build_import_graph(tmp_path, "bin")["bin.main"] == set()


def test_acyclic_chain_has_no_cycles():
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert strongly_connected(graph) == []


def test_cycles_are_found_and_ordered_by_size():
    graph = {
        "a": {"b"}, "b": {"c"}, "c": {"a"},          # 3-cycle
        "x": {"y"}, "y": {"x"},                       # 2-cycle
        "lone": set(),
    }
    components = strongly_connected(graph)
    assert [len(c) for c in components] == [3, 2]


def test_scc_handles_deep_chain_without_recursion_error():
    """Tarjan must be iterative: a deep import chain is ordinary in real repos."""
    depth = 3000
    graph = {f"m{i}": {f"m{i + 1}"} for i in range(depth)}
    graph[f"m{depth}"] = set()
    assert strongly_connected(graph) == []


# ---------------------------------------------------------- propagation cost


def test_propagation_cost_is_transitive_not_direct():
    """a -> b -> c means a reaches c.

    Measuring only direct edges reports a deep chain as loosely coupled, which
    is the opposite of true.
    """
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    # reachable pairs: a->b, a->c, b->c = 3 of 9
    assert propagation_cost(graph) == pytest.approx(3 / 9)


def test_propagation_cost_of_isolated_modules_is_zero():
    assert propagation_cost({"a": set(), "b": set()}) == 0.0


def test_propagation_cost_rises_when_a_hub_is_introduced():
    loose = {"a": set(), "b": set(), "c": set()}
    hub = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert propagation_cost(hub) > propagation_cost(loose)


# ------------------------------------------------- the motivating regression


def test_decomposition_into_a_cycle_is_not_reported_as_improvement(tmp_path):
    """The failure this tool exists to catch.

    One large module is split into small ones that still import the parent at
    runtime — the exact shape found in the repository that motivated this tool,
    where per-file complexity fell 44% while the largest cycle grew 2 -> 14.

    Complexity per file must fall (the split was real work) AND the cycle must be
    reported (the pieces are not independent). A tool that reports only the first
    would score this as a clean win.
    """
    before = tmp_path / "before"
    body = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
    write(before, "pkg/__init__.py", "")
    write(before, "pkg/big.py", f"def dispatch(x):\n{body}    return None\n")
    first = measure_tree(before, "pkg")

    after = tmp_path / "after"
    handlers = [f"h{i}" for i in range(6)]
    write(
        after,
        "pkg/__init__.py",
        "".join(f"from pkg.{h} import handle as handle_{h}\n" for h in handlers),
    )
    for h in handlers:
        write(
            after,
            f"pkg/{h}.py",
            "import pkg as _parent\n\n"
            "def handle(x):\n"
            "    if x:\n"
            "        return _parent\n"
            "    return None\n",
        )
    second = measure_tree(after, "pkg")

    assert second.complexity_per_file < first.complexity_per_file
    assert second.largest_cycle == len(handlers) + 1
    assert second.modules_in_cycles > first.modules_in_cycles
    assert first.cycles == 0


# ------------------------------------------------------------------ history


def _init_repo(path: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)


def _commit(path: pathlib.Path, message: str, when: str) -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", message],
        check=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
            "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def test_series_measures_every_point_with_the_same_definition(tmp_path):
    """Every point is re-derived from source, so a trend cannot be an artifact.

    This is the property that made the motivating result trustworthy after two
    earlier readings of a stored baseline produced opposite wrong answers.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    write(repo, "pkg/__init__.py", "")
    write(repo, "pkg/a.py", "def f(x):\n    if x:\n        return 1\n    return 0\n")
    _commit(repo, "one", "2026-01-05T12:00:00")

    write(repo, "pkg/b.py", "def g(x):\n    for i in x:\n        pass\n")
    write(repo, "pkg/c.py", "from pkg import b\n")
    _commit(repo, "two", "2026-02-05T12:00:00")

    series = measure_series(repo, "pkg", "2026-01-10", "2026-02-20", step_days=20)

    assert len(series) >= 2
    assert series[0].files < series[-1].files
    assert series[0].complexity < series[-1].complexity
    assert series[-1].edges > series[0].edges
    assert all(s.date for s in series)
    assert all(s.commit for s in series)


def test_importing_a_submodule_also_depends_on_its_package(tmp_path):
    """`from pkg import b` is two real edges, not one.

    Importing `pkg.b` executes `pkg/__init__.py` first, so the importer depends
    on the package as well as the submodule. Dropping the package edge would hide
    the most common real cycle there is: a package whose `__init__` imports its
    own submodules while those submodules import back into the package.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/b.py", "VALUE = 1\n")
    write(tmp_path, "pkg/c.py", "from pkg import b\n")
    graph = build_import_graph(tmp_path, "pkg")
    assert graph["pkg.c"] == {"pkg", "pkg.b"}

    # and that is what makes the package/submodule cycle detectable
    write(tmp_path, "pkg/__init__.py", "from pkg.c import *\n")
    assert measure_tree(tmp_path, "pkg").largest_cycle == 2


def test_series_leaves_no_worktree_behind(tmp_path):
    """Measuring history must not mutate the repository being measured."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    write(repo, "pkg/__init__.py", "")
    write(repo, "pkg/a.py", "def f():\n    return 1\n")
    _commit(repo, "one", "2026-01-05T12:00:00")

    measure_series(repo, "pkg", "2026-01-10", "2026-01-20", step_days=10)

    listed = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()
    assert len(listed) == 1  # the main checkout only


# ------------------------------------------------- provenance and the payer
#
# These cover the two properties that make a number usable by someone who did
# not run it: that it can be re-derived, and that it has been joined to
# somebody's cost. Both are failures this repository actually had.


from tools import structure_payer as payer  # noqa: E402
from tools import structure_provenance as provenance  # noqa: E402


def test_measurements_under_different_config_are_not_comparable():
    """The splice guard: two definitions must never be differenced silently.

    A radon de-duplication fix changed what 'complexity' meant mid-series here,
    and a 39% rise read as a 14% fall for three months because nothing recorded
    which definition produced which number.
    """
    first = provenance.build(repo=".", input_sha="a" * 40, recipe="x",
                             config={"package": "pkg", "counts": "import-time"})
    same = provenance.build(repo=".", input_sha="b" * 40, recipe="x",
                            config={"package": "pkg", "counts": "import-time"})
    other = provenance.build(repo=".", input_sha="b" * 40, recipe="x",
                             config={"package": "pkg", "counts": "all edges"})
    assert first.comparable_to(same), "same definition should be comparable"
    assert not first.comparable_to(other), "a changed definition compared as if identical"


def test_config_digest_changes_when_any_input_to_the_answer_changes():
    base = provenance.config_digest({"package": "pkg", "exclude": []})
    assert base != provenance.config_digest({"package": "other", "exclude": []})
    assert base != provenance.config_digest({"package": "pkg", "exclude": ["tests/"]})


def test_dirty_measuring_code_is_announced_not_silently_stamped():
    """A sha that names something other than what ran is worse than no sha."""
    clean = provenance.Provenance(tool_sha="abc123", tool_dirty=False)
    dirty = provenance.Provenance(tool_sha="abc123", tool_dirty=True)
    assert clean.warning() == ""
    assert "uncommitted" in dirty.warning()


def test_the_tool_offers_no_way_to_supply_a_stored_baseline():
    """Deriving both sides is structural here, not a convention.

    If a --baseline flag ever appears, a change can pass by editing a file
    instead of by improving the code. Keeping the tool unable to accept one is
    the guarantee; this test is what makes adding one a deliberate act.
    """
    from tools.measure_structure import main

    for flag in ("--baseline", "--known-violations", "--against"):
        with pytest.raises(SystemExit) as raised:
            main(["tree", ".", "pkg", flag, "somefile.json"])
        assert raised.value.code != 0, f"{flag} was accepted"


def _row(module, *, reached_by, changes, fixes=0):
    return payer.ModulePayer(module=module, reached_by=reached_by,
                             changes=changes, fixes=fixes)


def test_exposed_but_unpaid_module_is_monitor_not_refactor():
    """The rule the literature and our own data both insist on.

    cake's 114-module tangle holds 34% of change activity but only 20% of fix
    activity, and its commits are smaller than average. Structure alone would
    have called it debt; it is not a refactor candidate.
    """
    rows = [
        _row("exposed.idle", reached_by=500, changes=0),
        _row("exposed.busy", reached_by=500, changes=40),
        _row("local.busy", reached_by=1, changes=40),
        _row("local.idle", reached_by=1, changes=0),
    ]
    buckets = payer.quadrants(rows)
    names = {k: {r.module for r in v} for k, v in buckets.items()}
    assert "exposed.idle" in names["monitor"], "unpaid structure offered as a refactor"
    assert "exposed.busy" in names["refactor"]
    assert "local.busy" in names["churn"], "contained cost mislabelled as exposure"


def test_ranking_uses_change_count_not_the_sparse_fix_signal():
    """Fix detection is message matching and finds ~1% of commits.

    Ordering by it puts noise at the top. The rank must use the better-powered
    observation, with fixes reported beside it.
    """
    noisy = _row("rarely.touched", reached_by=10, changes=1, fixes=3)
    real = _row("hot.and.exposed", reached_by=400, changes=50, fixes=0)
    assert real.score > noisy.score
    ordered = payer.quadrants([noisy, real])
    top = (ordered["refactor"] or ordered["churn"] or ordered["monitor"])[0]
    assert top.module == "hot.and.exposed"


def test_zero_complexity_module_can_still_be_a_refactor_candidate():
    """The finding that justifies this whole join.

    cake's top candidate is `cake/__init__.py`: 258 changes, reached by 396
    modules, cyclomatic complexity 0. A complexity-only ratchet cannot see it
    at any threshold.
    """
    rows = [
        payer.ModulePayer(module="pkg", complexity=0, reached_by=396, changes=258),
        payer.ModulePayer(module="pkg.leaf", complexity=200, reached_by=0, changes=1),
    ]
    buckets = payer.quadrants(rows)
    assert "pkg" in {r.module for r in buckets["refactor"]}


def test_underpowered_defect_oracle_says_so():
    rows = [_row("a", reached_by=5, changes=2)]
    stats = {"commits": 1000, "commits_touching_package": 100,
             "fix_commits": 3, "fix_share": 0.003, "fix_pattern": "fix"}
    assert "UNDERPOWERED" in payer.render(rows, stats)


def test_transitive_reach_follows_chains_and_cycles():
    graph = {"a": {"b"}, "b": {"c"}, "c": set(), "x": {"y"}, "y": {"x"}}
    reach = payer.transitive_reach(graph)
    assert reach["a"] == 2, "chain reach not transitive"
    assert reach["c"] == 0
    assert reach["x"] == 2, "cycle members must reach themselves and each other"


def test_reverse_graph_gives_who_depends_on_me():
    graph = {"core": set(), "one": {"core"}, "two": {"core"}}
    assert payer.transitive_reach(payer.reverse(graph))["core"] == 2


def test_falling_ratio_over_a_growing_denominator_is_flagged():
    """A ratio can improve while the thing it measures gets worse.

    Real numbers from cake between 2026-07-01 and HEAD: propagation cost went
    19.08% -> 18.10%, which reads as an improvement, while reachable pairs went
    57,922 -> 88,926. Reporting only the ratio hides a 53% growth in blast
    radius, and that is precisely how it went unremarked here.
    """
    from tools.measure_structure import Structure, render_compare

    before = Structure(commit="aaa", modules=551, propagation_cost=0.1908)
    after = Structure(commit="bbb", modules=701, propagation_cost=0.1810)

    report = render_compare(before, after)

    pairs_before = f"{0.1908 * 551 ** 2:,.0f}"
    pairs_after = f"{0.1810 * 701 ** 2:,.0f}"
    assert pairs_before in report and pairs_after in report, \
        "the quantity was not reported beside the ratio"
    assert "NOTE" in report, "a falling ratio over a growing base was not flagged"
    # The ratio fell; the quantity rose by more than half. Both must be visible.
    assert float(pairs_after.replace(",", "")) > float(pairs_before.replace(",", ""))


def test_growing_file_count_is_not_scored_as_better_or_worse():
    """Rewarding fewer files rewards deletion, and punishing growth punishes work."""
    from tools.measure_structure import Structure, render_compare

    report = render_compare(Structure(commit="a", files=10), Structure(commit="b", files=99))
    files_line = next(l for l in report.splitlines() if l.strip().startswith("files"))
    assert "better" not in files_line and "worse" not in files_line
