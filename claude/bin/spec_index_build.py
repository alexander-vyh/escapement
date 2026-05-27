#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7,<4",
# ]
# ///
"""Build the spec index for the openspec-beads-staleness classifier.

Walking-skeleton task 1.1 from openspec/changes/openspec-beads-staleness/tasks.md.

## What this does

Walks `openspec/changes/*/specs/*.md` (excluding `archive/`) AND
`openspec/specs/*.md` if it exists. Parses each `### Requirement: <name>`
block in those spec files, extracts the requirement's description and
scenario text, embeds the combined text with
`sentence-transformers/all-MiniLM-L6-v2`, and persists the result to
`.beads/.spec-index.json`.

## Output shape

```json
{
  "schema_version": 1,
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "built_at": "2026-05-27T08:00:00+00:00",
  "requirements": [
    {
      "requirement_id": "spec-area-classifier.index-spec-corpus-from-openspec-directories",
      "source_path": "openspec/changes/openspec-beads-staleness/specs/spec-area-classifier.md",
      "capability": "spec-area-classifier",
      "name": "Index spec corpus from openspec directories",
      "text": "<combined text for embedding>",
      "keywords": ["index", "spec", "corpus", ...],
      "embedding": [0.012, -0.034, ...]   // 384 floats
    },
    ...
  ]
}
```

## Usage

    uv run claude/bin/spec_index_build.py
    # or: ./claude/bin/spec_index_build.py  (the shebang triggers uv)

The first run downloads the ~80 MB MiniLM model into uv's cache.
Subsequent runs are fast.

## archive/** exclusion is a named tested invariant

Per `claude/rules/delicate-art-of-bureaucracy.md` and the design.md:
archived *change records* live under `openspec/changes/archive/`. Their
*specs* (when promoted via `openspec archive`) live in top-level
`openspec/specs/`. Treating archived change records as still-spec'd
area would produce false positives forever on every closed bug
touching that area. This script explicitly skips `archive/`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_EMBED_DIM = 384  # all-MiniLM-L6-v2 produces 384-dim vectors

_REQUIREMENT_RE = re.compile(
    r"^###\s+Requirement:\s+(.+?)\s*$", re.MULTILINE
)
_SCENARIO_RE = re.compile(
    r"^####\s+Scenario:\s+(.+?)\s*$", re.MULTILINE
)
_PURPOSE_RE = re.compile(
    r"^##\s+Purpose\s*\n(.+?)(?=\n##\s|\Z)", re.MULTILINE | re.DOTALL
)
_CAPABILITY_COMMENT_RE = re.compile(
    r"<!--\s*Spec:\s*([a-z0-9][a-z0-9-]*)\s*-->", re.IGNORECASE
)

# Stop-words plus markdown-noise tokens to skip when extracting keywords.
_KEYWORD_STOP = frozenset({
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "at", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "should",
    "must", "shall", "may", "can", "this", "that", "these", "those", "it",
    "its", "their", "such", "which", "what", "when", "where", "how",
    "why", "if", "but", "not", "no", "yes", "any", "all", "some", "more",
    "less", "than", "then", "so", "very", "also", "into", "out", "up",
    "down", "over", "under", "again", "each", "other", "well", "very",
    "purpose", "scenario", "requirement", "given", "when", "then", "and",
})


def find_spec_files(project_dir: Path) -> list[Path]:
    """Return all spec markdown files under openspec/changes/*/specs/ AND
    openspec/specs/, excluding the archive/ directory.

    This is the named, tested archive/** exclusion invariant.
    """
    out: list[Path] = []

    changes_dir = project_dir / "openspec" / "changes"
    if changes_dir.is_dir():
        for change_dir in changes_dir.iterdir():
            if not change_dir.is_dir():
                continue
            if change_dir.name == "archive":  # named invariant
                continue
            specs_subdir = change_dir / "specs"
            if specs_subdir.is_dir():
                out.extend(p for p in specs_subdir.glob("*.md") if p.is_file())

    top_specs = project_dir / "openspec" / "specs"
    if top_specs.is_dir():
        out.extend(p for p in top_specs.glob("*.md") if p.is_file())

    return sorted(out)


def parse_capability_name(content: str, fallback: str) -> str:
    """Extract the capability name from a `<!-- Spec: <name> -->` comment,
    falling back to the spec file's basename.
    """
    m = _CAPABILITY_COMMENT_RE.search(content)
    if m:
        return m.group(1).strip().lower()
    return fallback


def parse_purpose(content: str) -> str:
    """Extract the text under `## Purpose`, stopping at the next `## ` heading."""
    m = _PURPOSE_RE.search(content)
    if not m:
        return ""
    return m.group(1).strip()


def parse_requirements(content: str) -> list[dict[str, str]]:
    """Parse `### Requirement: <name>` blocks with their description and
    scenario text. Returns a list of dicts.
    """
    requirements: list[dict[str, str]] = []
    matches = list(_REQUIREMENT_RE.finditer(content))
    for idx, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        block = content[start:end]

        # Description: everything up to the first scenario
        scenario_match = _SCENARIO_RE.search(block)
        if scenario_match:
            description = block[:scenario_match.start()].strip()
        else:
            description = block.strip()

        # Scenario text: concatenate all scenario blocks (name + body)
        scenarios = []
        scenario_starts = [s.start() for s in _SCENARIO_RE.finditer(block)]
        if scenario_starts:
            scenario_starts.append(len(block))
            for i in range(len(scenario_starts) - 1):
                scenario_text = block[scenario_starts[i]:scenario_starts[i + 1]].strip()
                scenarios.append(scenario_text)

        requirements.append({
            "name": name,
            "description": description,
            "scenarios": "\n\n".join(scenarios),
        })
    return requirements


def kebab_case(name: str) -> str:
    """Kebab-case a requirement name for use as an anchor / id segment."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def extract_keywords(text: str, max_count: int = 20) -> list[str]:
    """Cheap keyword extraction: lowercase alphanumeric tokens, dedup,
    drop stop-words, take the first N by appearance order.
    """
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t in _KEYWORD_STOP:
            continue
        if t in seen:
            continue
        seen.add(t)
        result.append(t)
        if len(result) >= max_count:
            break
    return result


def build_embedding_text(purpose: str, req: dict[str, str]) -> str:
    """Combine capability purpose + requirement description + scenarios into
    the single string we embed. Purpose gives global context; the
    description names the requirement; scenarios give concrete behavioral
    examples that anchor the embedding.
    """
    parts = []
    if purpose:
        parts.append(f"Purpose: {purpose}")
    parts.append(f"Requirement: {req['name']}")
    if req["description"]:
        parts.append(req["description"])
    if req["scenarios"]:
        parts.append(req["scenarios"])
    return "\n\n".join(parts)


def build_index(project_dir: Path) -> dict[str, Any]:
    """Build the full spec index dict ready to serialize to JSON.

    Embeddings are computed in one batch for efficiency.
    """
    from sentence_transformers import SentenceTransformer

    spec_files = find_spec_files(project_dir)
    if not spec_files:
        return {
            "schema_version": 1,
            "model": _MODEL_NAME,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "requirements": [],
            "stats": {"spec_files": 0, "requirements": 0},
        }

    # Parse all specs first, build a list of (requirement_entry, text_to_embed)
    pending: list[tuple[dict[str, Any], str]] = []
    for spec_path in spec_files:
        try:
            content = spec_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        capability = parse_capability_name(
            content, fallback=spec_path.stem
        )
        purpose = parse_purpose(content)
        requirements = parse_requirements(content)

        rel_path = str(spec_path.relative_to(project_dir))
        for req in requirements:
            embedding_text = build_embedding_text(purpose, req)
            entry: dict[str, Any] = {
                "requirement_id": f"{capability}.{kebab_case(req['name'])}",
                "source_path": rel_path,
                "capability": capability,
                "name": req["name"],
                "text": embedding_text,
                "keywords": extract_keywords(embedding_text),
                # embedding: filled in after batch encode
            }
            pending.append((entry, embedding_text))

    # Batch-encode all texts
    if pending:
        model = SentenceTransformer(_MODEL_NAME)
        texts = [t for _, t in pending]
        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        for (entry, _), vec in zip(pending, embeddings):
            entry["embedding"] = vec.tolist()
            if len(entry["embedding"]) != _EMBED_DIM:
                # Loud failure: model produced unexpected dimension
                raise RuntimeError(
                    f"unexpected embedding dim: {len(entry['embedding'])} "
                    f"!= {_EMBED_DIM} (model: {_MODEL_NAME})"
                )

    requirements_out = [entry for entry, _ in pending]
    return {
        "schema_version": 1,
        "model": _MODEL_NAME,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requirements": requirements_out,
        "stats": {
            "spec_files": len(spec_files),
            "requirements": len(requirements_out),
        },
    }


def _resolve_project_dir() -> Path:
    """Find the repo root by walking up from cwd looking for .beads/."""
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".beads").is_dir():
            return parent
    # Fallback: cwd
    return cwd


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project root to build the index for. Default: walk up from cwd to find .beads/.",
    )
    args = parser.parse_args()

    if args.project_dir is not None:
        project_dir = args.project_dir.resolve()
    else:
        project_dir = _resolve_project_dir()

    beads_dir = project_dir / ".beads"
    if not beads_dir.is_dir():
        # Allow building against a project that doesn't yet have .beads/ — useful
        # for fixtures. Create the directory if missing.
        beads_dir.mkdir(parents=True, exist_ok=True)

    output_path = beads_dir / ".spec-index.json"

    index = build_index(project_dir)

    # Atomic write: write to a tmp file then rename
    tmp_path = output_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(output_path)

    stats = index.get("stats", {})
    print(
        f"Built spec index: {stats.get('requirements', 0)} requirements "
        f"from {stats.get('spec_files', 0)} spec file(s) → {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
