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
    """`from pkg.mod import name` is an edge to pkg.mod.

    Resolving it to the non-existent module `pkg.mod.name` drops the edge and
    silently reports a system as less connected than it is.
    """
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/mod.py", "VALUE = 1\n")
    write(tmp_path, "pkg/user.py", "from pkg.mod import VALUE\n")
    graph = build_import_graph(tmp_path, "pkg")
    assert graph["pkg.user"] == {"pkg.mod"}


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
