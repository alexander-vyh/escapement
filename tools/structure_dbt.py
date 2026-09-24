#!/usr/bin/env python3
"""Structure of a dbt project, read from its compiled manifest.

`cake` is half SQL — 1,952 tracked `.sql` files against 1,951 Python — and the
instrument measured none of it. Half a repository reading as absent is not a
smaller version of the truth; it is a different claim.

SQL is not parsed here and never should be. dbt already resolves `ref()` and
`source()` into an exact dependency graph and writes it to
`target/manifest.json`, so the adapter reads that artifact instead of guessing
at 1,016 files' worth of Jinja-templated SQL.

That makes this the one place the instrument consumes a STORED measurement
rather than deriving one, which is exactly what the rest of this tool refuses
to do. The compromise is bounded by making the staleness visible: the manifest
carries its own generation time, and this module compares it against the
modification times of the SQL it describes. A manifest older than the models it
claims to describe is reported, not silently trusted — an unannounced stale
artifact is how a three-month-old complexity baseline went on being quoted as
current.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

MANIFEST_CANDIDATES = (
    "target/manifest.json",
    "dbt/target/manifest.json",
    "transform/target/manifest.json",
)


@dataclasses.dataclass
class Manifest:
    path: pathlib.Path
    generated_at: str
    dbt_version: str
    models: dict[str, list[str]]          # repo-relative sql path -> upstream paths
    unresolved: int = 0                   # edges pointing outside the model set
    stale: list[str] = dataclasses.field(default_factory=list)

    @property
    def fresh(self) -> bool:
        return not self.stale


def find(repo: str | pathlib.Path) -> pathlib.Path | None:
    root = pathlib.Path(repo)
    for candidate in MANIFEST_CANDIDATES:
        path = root / candidate
        if path.exists():
            return path
    return None


def load(repo: str | pathlib.Path, path: pathlib.Path | None = None) -> Manifest | None:
    """Read the model graph, keyed by repository-relative SQL path.

    dbt records paths relative to the dbt project directory, so they are
    rebased onto the repository root here: a graph whose keys do not match
    `git ls-files` output silently matches nothing, and reports as an empty
    result rather than as an error.
    """
    root = pathlib.Path(repo)
    path = path or find(root)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    project_root = path.parent.parent          # <project>/target/manifest.json
    prefix = project_root.relative_to(root) if project_root != root else pathlib.Path()

    nodes = raw.get("nodes", {})
    by_id: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        rel = node.get("original_file_path")
        if rel:
            by_id[node_id] = str(prefix / rel) if prefix.parts else rel

    models: dict[str, list[str]] = {}
    unresolved = 0
    for node_id, rel in by_id.items():
        upstream = []
        for dep in nodes.get(node_id, {}).get("depends_on", {}).get("nodes", []):
            target = by_id.get(dep)
            if target:
                upstream.append(target)
            else:
                # A source, seed, or snapshot: a real edge whose other end is
                # not a model file. Counted rather than dropped, so a graph
                # that looks sparse can be told apart from one that is.
                unresolved += 1
        models[rel] = upstream

    manifest = Manifest(
        path=path,
        generated_at=raw.get("metadata", {}).get("generated_at", "unknown"),
        dbt_version=raw.get("metadata", {}).get("dbt_version", "unknown"),
        models=models,
        unresolved=unresolved,
    )
    manifest.stale = _stale_models(root, manifest)
    return manifest


def described_files(repo: str | pathlib.Path, manifest: Manifest | None = None) -> set[str]:
    """Every repository-relative SQL path the manifest accounts for.

    Broader than the model DAG deliberately. `cake` tracks 547 models and 681
    data tests; the tests are first-party SQL that dbt fully resolves, so
    reporting them as unmeasured would understate coverage by more than the
    models themselves. The DAG stays models-only — a test is a leaf assertion,
    not a transformation edge — but coverage counts everything dbt can see.
    """
    root = pathlib.Path(repo)
    path = find(root)
    if path is None:
        return set()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    project_root = path.parent.parent
    prefix = project_root.relative_to(root) if project_root != root else pathlib.Path()
    seen: set[str] = set()
    for group in ("nodes", "sources", "macros", "exposures"):
        for node in raw.get(group, {}).values():
            rel = node.get("original_file_path")
            if rel and rel.endswith(".sql"):
                seen.add(str(prefix / rel) if prefix.parts else rel)
    return seen


def _stale_models(root: pathlib.Path, manifest: Manifest, limit: int = 20) -> list[str]:
    """Models edited after the manifest was generated.

    These are the files whose recorded structure is known to be out of date.
    The check is cheap and the alternative is quoting a graph that describes
    code nobody is running any more.
    """
    try:
        cutoff = manifest.path.stat().st_mtime
    except OSError:
        return []
    late = []
    for rel in manifest.models:
        source = root / rel
        try:
            if source.stat().st_mtime > cutoff:
                late.append(rel)
        except OSError:
            continue
        if len(late) >= limit:
            break
    return late


def render(manifest: Manifest | None) -> str:
    if manifest is None:
        return ("  dbt       no manifest found. SQL structure comes from "
                "`dbt parse`, never from a SQL parser.")
    lines = [
        f"  dbt       {len(manifest.models):,} models from {manifest.path}",
        f"            generated {manifest.generated_at} by dbt {manifest.dbt_version}",
        f"            {manifest.unresolved:,} edges to sources/seeds outside the model set",
    ]
    if manifest.stale:
        lines += [
            f"            STALE: {len(manifest.stale)} model(s) edited after this "
            f"manifest was generated,",
            f"            starting with {manifest.stale[0]}. Re-run `dbt parse` "
            f"before trusting the graph.",
        ]
    return "\n".join(lines)
