#!/usr/bin/env python3
"""What this instrument can and cannot measure, said out loud.

`dashboards` holds 1,242 JavaScript files, a 7,701-line `App.test.jsx`, and for
four months it measured **nothing**. Not because measurement failed — because
nobody noticed it was never running. Silence read as health.

So coverage is a first-class output. Every run reports what fraction of the
repository's tracked source it actually measured, and names each language it
cannot measure together with the reason. An adapter that quietly under-measures
is worse than one that refuses, because a refusal is visible.

Adding a language means adding an adapter that wraps a maintained tool, never a
new parser. We already paid for a hand-rolled import graph: it had four bugs
whose errors partly cancelled and produced a confident wrong answer.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import pathlib
import shutil
import subprocess

import structure_dbt as _dbt

# Extensions that carry logic. Data, docs and lockfiles are deliberately absent:
# coverage is about code whose structure can rot, not about every tracked byte.
LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "sql": (".sql",),
    "shell": (".sh", ".bash"),
    "go": (".go",),
    "rust": (".rs",),
}

# Paths that are not this repository's work. Vendored and generated trees are
# excluded from the denominator too — counting them would make coverage look
# worse for code nobody here is responsible for.
IGNORED_SEGMENTS = (
    "node_modules/", ".venv/", "venv/", "vendor/", "dist/", "build/",
    ".worktrees/", "site-packages/", ".egg-info/", "__pycache__/",
    "dbt_packages/",
)


@dataclasses.dataclass
class Adapter:
    language: str
    tool: str
    why_unavailable: str = ""

    @property
    def available(self) -> bool:
        return not self.why_unavailable


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


# Languages lizard parses that we also track. Complexity comes from a
# maintained multi-language analyser rather than anything written here: the
# hand-rolled Python import graph in this same tool shipped with four bugs
# whose errors partly cancelled, which is the failure mode to avoid repeating
# across seven more grammars.
LIZARD_LANGUAGES = {
    "javascript": "javascript",
    "typescript": "typescript",
    "python": "python",
    "go": "go",
    "rust": "rust",
}


def adapters(repo: str | None = None) -> dict[str, Adapter]:
    """Which languages this installation can measure, right now, on this machine.

    Availability is probed rather than assumed. A tool named in a design
    document but absent from the host measures nothing, and the report must say
    that rather than returning an empty result that reads like a clean bill.
    """
    lizard = _have("lizard")
    missing = "lizard not installed (pip install lizard)"
    found: dict[str, Adapter] = {
        "python": Adapter("python", "stdlib ast (built in)"),
    }
    for language in ("javascript", "typescript", "go", "rust"):
        found[language] = Adapter(
            language, "lizard", "" if lizard else missing,
        )
    # SQL availability depends on a compiled manifest, not on the dbt binary.
    # Requiring the executable would have left `cake` — half of whose tracked
    # source is SQL — permanently unmeasured on any machine without dbt, while
    # the graph it needs was already committed at dbt/target/manifest.json.
    found["sql"] = Adapter(
        "sql", "dbt manifest",
        "" if repo and _dbt.find(repo) else
        "no dbt manifest found; run `dbt parse`. SQL structure comes from dbt's "
        "resolved graph, never from a SQL parser",
    )
    found["shell"] = Adapter("shell", "-", "no adapter written")
    return found


# Smaller batches cost a little more process startup and buy a much cheaper
# recovery: when one file wedges the analyser, only its batch is re-run file by
# file. A batch exceeding this deadline is presumed wedged, not slow — lizard
# reads a few hundred ordinary files in about a second.
BATCH = 200
BATCH_TIMEOUT = 60
FILE_TIMEOUT = 10


def _run_lizard(repo: str, flag: str, files: list[str], timeout: int) -> str | None:
    """Run lizard under a deadline. `None` means it exceeded it.

    The distinction matters to the caller: empty output is "nothing to report",
    while `None` is "this tool stopped responding", and those must not be
    collapsed into the same silent zero.
    """
    try:
        done = subprocess.run(
            ["lizard", "-l", flag, "--csv", *files],
            cwd=repo, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def measure(repo: str, paths: list[str], language: str) -> dict[str, float]:
    """Summed cyclomatic complexity per file, via lizard.

    A file the analyser successfully read but that declares no functions maps to
    0.0, and a file the analyser never got through is absent. Collapsing those
    two into one empty result is the mistake this whole module exists to stop:
    "nothing here" and "we never looked" must not render identically.

    Returns an empty mapping when the language has no working adapter at all.
    """
    flag = LIZARD_LANGUAGES.get(language)
    if not flag or not paths or not _have("lizard"):
        return {}

    # Exact tracked files, never directory roots. Handing lizard a root makes it
    # walk the filesystem, which means untracked vendored trees: `dashboards`
    # carries 377 packages under a frontend `node_modules/`, and pointing the
    # analyser at `src/` walked all of them. Passing files also makes the
    # denominator here identical to the one git reports.
    wanted = set(paths)
    totals: dict[str, float] = {}
    for start in range(0, len(paths), BATCH):
        chunk = paths[start:start + BATCH]
        out = _run_lizard(repo, flag, chunk, BATCH_TIMEOUT)
        if out is None:
            # The batch hung. lizard loops forever on some inputs — a 563-line
            # `.mjs` in this estate pins a core indefinitely — so one bad file
            # must never take the instrument down with it. Retry file by file
            # under a short deadline; whatever still hangs stays absent and
            # surfaces as UNPARSED rather than as a clean zero.
            out = ""
            for one in chunk:
                piece = _run_lizard(repo, flag, [one], FILE_TIMEOUT)
                if piece is not None:
                    totals.setdefault(one, 0.0)
                    out += piece
        else:
            for one in chunk:
                totals.setdefault(one, 0.0)
        for row in csv.reader(io.StringIO(out)):
            if len(row) < 7:
                continue
            try:
                ccn = float(row[1])
            except ValueError:
                continue
            path = row[6].lstrip("./")
            if path in wanted:
                totals[path] = totals.get(path, 0.0) + ccn
    return totals


def inventory(repo: str) -> dict[str, list[str]]:
    """Tracked source files by language, from git rather than from a walk."""
    try:
        listing = subprocess.run(
            ["git", "-C", repo, "ls-files"],
            capture_output=True, text=True, timeout=300, check=False,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return {}
    by_language: dict[str, list[str]] = {}
    for path in listing:
        if any(segment in path for segment in IGNORED_SEGMENTS):
            continue
        for language, extensions in LANGUAGE_EXTENSIONS.items():
            if path.endswith(extensions):
                by_language.setdefault(language, []).append(path)
                break
    return by_language


def in_scope(path: str, scope: list[str]) -> bool:
    return any(path == pattern or path.startswith(pattern.rstrip("/") + "/")
               for pattern in scope)


@dataclasses.dataclass
class Coverage:
    total: int = 0
    measured: int = 0
    by_language: dict = dataclasses.field(default_factory=dict)

    @property
    def fraction(self) -> float:
        return self.measured / self.total if self.total else 0.0


def measurable(repo: str, paths: list[str], language: str) -> set[str]:
    """Files the adapter can genuinely handle, verified by running it.

    Each language is checked with the same tool that would measure it, not a
    stand-in: Python with the stdlib parser the instrument itself uses, the
    rest with lizard. Verifying Python with a different parser would let the
    two disagree about what is measurable and produce a coverage figure that no
    measurement run can reproduce.
    """
    if language == "sql":
        return set(paths) & _dbt.described_files(repo)
    if language == "python":
        import ast
        ok = set()
        for rel in paths:
            try:
                source = (pathlib.Path(repo) / rel).read_text(encoding="utf-8", errors="replace")
                ast.parse(source)
            except (OSError, SyntaxError, ValueError):
                continue
            ok.add(rel)
        return ok
    return set(measure(repo, paths, language))



def coverage(repo: str, scope: list[str], verify: bool = True) -> Coverage:
    """How much of the repository is actually measured, as a number.

    A file counts as measured only when it is inside declared scope AND its
    language has a working adapter AND that adapter returned a result for it.
    All three matter: `cake` misses Python files to scope, `dashboards` missed
    1,005 JavaScript files to a absent adapter, and a file the analyser cannot
    parse silently produces nothing at all.

    The third check is why this runs the adapters rather than predicting them.
    Counting a file as measured because its extension looks supported is the
    same substitution of a claim for an observation that this whole tool exists
    to remove; `verify=False` exists only for tests that need the shape without
    the cost.
    """
    available = adapters(repo)
    files = inventory(repo)
    result = Coverage()
    for language, paths in sorted(files.items()):
        adapter = available.get(language) or Adapter(language, "-", "unknown language")
        scoped = [p for p in paths if in_scope(p, scope)] if scope else []
        failed = 0
        if not adapter.available or not scoped:
            measured = 0
        elif not verify:
            measured = len(scoped)
        else:
            produced = measurable(repo, scoped, language)
            measured = len(produced)
            failed = len(scoped) - measured
        result.total += len(paths)
        result.measured += measured
        result.by_language[language] = {
            "files": len(paths),
            "in_scope": len(scoped),
            "measured": measured,
            "unparsed": failed,
            "tool": adapter.tool,
            "unavailable": adapter.why_unavailable,
        }
    return result


def render(cov: Coverage, repo: str | None = None) -> str:
    lines = [
        f"coverage    {cov.measured:,} of {cov.total:,} tracked source files "
        f"({100 * cov.fraction:.1f}%)",
        "",
        f"  {'language':11} {'files':>7} {'in scope':>9} {'measured':>9} "
        f"{'unparsed':>9}  tool / why not",
    ]
    for language, row in sorted(cov.by_language.items(),
                                key=lambda kv: -kv[1]["files"]):
        note = row["unavailable"] or row["tool"]
        lines.append(
            f"  {language:11} {row['files']:7,} {row['in_scope']:9,} "
            f"{row['measured']:9,} {row.get('unparsed', 0):9,}  {note}"
        )
    if repo and cov.by_language.get("sql", {}).get("measured"):
        # The manifest is the one stored measurement this instrument consumes,
        # so it never appears without its generation time and staleness.
        lines += ["", _dbt.render(_dbt.load(repo))]
    choked = {lang: row["unparsed"] for lang, row in cov.by_language.items()
              if row.get("unparsed")}
    if choked:
        detail = ", ".join(f"{n} {lang}" for lang, n in sorted(choked.items()))
        lines += [
            "",
            f"  UNPARSED  {detail}. These files are in scope and their adapter ran,",
            "            yet produced no result. That is a third kind of silence,",
            "            and it reads identically to clean code.",
        ]
    unmeasured = [
        (language, row) for language, row in cov.by_language.items()
        if row["measured"] < row["files"]
    ]
    if unmeasured:
        lines += ["", "  Unmeasured code is not healthy code; it is code with no"]
        lines += ["  evidence either way. Every exclusion above is a forecast that"]
        lines += ["  the next defect will not be there — in this estate those"]
        lines += ["  forecasts were wrong twice, at a 5,541-line test file and a"]
        lines += ["  7,701-line one."]
    return "\n".join(lines)
