#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7,<4",
#     "numpy>=1.24",
# ]
# ///
"""Classify beads issues against the spec index.

Walking-skeleton task 2.2 from openspec/changes/openspec-beads-staleness/tasks.md.

## What this does

Loads the spec index produced by `spec_index_build.py` and a corpus of
bug fixtures. For each bug:

  - Embed the bug's title+body using the same model
    (`sentence-transformers/all-MiniLM-L6-v2`).
  - Cosine-similarity-score it against every requirement in the index.
  - Classify as "in" (spec'd area) if any requirement scores above the
    threshold; otherwise "out".
  - Emit a JSON record with the matched requirements (sorted by score)
    and a rationale text.

If the corpus has `expected_classification` and `expected_requirement_ids`
fields, compute accuracy and fail (exit 2) if it falls below the
threshold (default 0.9).

## Usage

    # Classify a corpus, fail if accuracy < 0.9 (riskiest-assumption test)
    uv run claude/bin/classify_bugs.py \\
        --corpus claude/bin/tests/fixtures/cake-bugs.json

    # One-off classification of a single bead
    echo '{"bug_id":"x-1","title":"foo","body":"bar"}' | \\
        uv run claude/bin/classify_bugs.py --stdin

## Output

```json
{
  "threshold": 0.6,
  "accuracy": 0.9,            // only if expected labels present
  "total": 10,
  "correct": 9,
  "results": [
    {
      "bug_id": "cake-abc",
      "classification": "in",
      "best_score": 0.72,
      "matched_requirements": [
        {"requirement_id": "spec-area-classifier.x", "score": 0.72},
        ...
      ],
      "rationale": "matched 2 requirement(s) above threshold 0.6 ..."
    },
    ...
  ]
}
```
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_DEFAULT_THRESHOLD = 0.6
_DEFAULT_ACCURACY_BAR = 0.9
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _resolve_project_dir() -> Path:
    import os
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".beads").is_dir():
            return parent
    return cwd


def load_index(project_dir: Path) -> dict[str, Any]:
    """Load .beads/.spec-index.json."""
    path = project_dir / ".beads" / ".spec-index.json"
    if not path.is_file():
        sys.stderr.write(
            f"error: spec index not found at {path}. "
            f"Run claude/bin/spec_index_build.py first.\n"
        )
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def cosine_similarity(a, b) -> float:
    """Cosine similarity for two pre-normalized vectors (built that way by
    sentence_transformers when normalize_embeddings=True)."""
    import numpy as np
    a = np.asarray(a, dtype="float32")
    b = np.asarray(b, dtype="float32")
    # If pre-normalized, dot product == cosine similarity.
    # We renormalize defensively in case the stored embeddings ever change.
    na = a / max(float(np.linalg.norm(a)), 1e-12)
    nb = b / max(float(np.linalg.norm(b)), 1e-12)
    return float(na @ nb)


def classify_bug(
    bug: dict[str, Any],
    bug_embedding,
    index: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    """Score a single bug against every indexed requirement; return the
    classification record.
    """
    scored = []
    for req in index["requirements"]:
        score = cosine_similarity(bug_embedding, req["embedding"])
        scored.append({
            "requirement_id": req["requirement_id"],
            "score": round(score, 4),
        })
    scored.sort(key=lambda x: -x["score"])
    matched = [s for s in scored if s["score"] >= threshold]

    best_score = scored[0]["score"] if scored else 0.0
    if matched:
        classification = "in"
        rationale = (
            f"matched {len(matched)} requirement(s) above threshold {threshold}; "
            f"top match {matched[0]['requirement_id']} at score {matched[0]['score']}"
        )
    else:
        classification = "out"
        rationale = (
            f"no requirements matched threshold {threshold}; "
            f"best near-miss {scored[0]['requirement_id']} at score {best_score}"
            if scored else "no spec index entries to match against"
        )

    return {
        "bug_id": bug.get("bug_id", bug.get("id", "unknown")),
        "title": bug.get("title", ""),
        "classification": classification,
        "best_score": best_score,
        "matched_requirements": matched[:10],  # cap the output
        "next_best": scored[1:4] if classification == "in" else [],
        "rationale": rationale,
    }


def embed_bugs(bugs: list[dict[str, Any]]):
    """Embed each bug's title+body and return a list of vectors aligned with
    the input order.
    """
    from sentence_transformers import SentenceTransformer
    texts = [
        f"{b.get('title', '')}\n\n{b.get('body', '')}".strip()
        for b in bugs
    ]
    model = SentenceTransformer(_MODEL_NAME)
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings


def evaluate_accuracy(results: list[dict[str, Any]], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare each result's classification to the corpus's expected label.

    Counts as correct iff:
    - classification matches expected ("in" or "out"), AND
    - if "in", at least one of the matched requirement_ids is in the
      expected_requirement_ids list (if that list is provided).
    """
    if not all("expected_classification" in b for b in corpus):
        return {"accuracy": None, "total": len(results), "correct": None}

    correct = 0
    details: list[dict[str, Any]] = []
    for result, bug in zip(results, corpus):
        expected = bug["expected_classification"]
        expected_reqs = bug.get("expected_requirement_ids", [])
        is_correct = result["classification"] == expected

        if is_correct and expected == "in" and expected_reqs:
            matched_ids = {m["requirement_id"] for m in result["matched_requirements"]}
            if not (matched_ids & set(expected_reqs)):
                # Got the classification right but matched the wrong requirement
                is_correct = False
                result["rationale"] += (
                    f" [accuracy: classification correct but matched IDs "
                    f"{sorted(matched_ids)[:3]} don't overlap with expected "
                    f"{expected_reqs[:3]}]"
                )

        if is_correct:
            correct += 1
        result["expected_classification"] = expected
        result["correct"] = is_correct
        details.append({
            "bug_id": result["bug_id"],
            "expected": expected,
            "got": result["classification"],
            "correct": is_correct,
        })

    total = len(results)
    return {
        "accuracy": correct / total if total else 0.0,
        "total": total,
        "correct": correct,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--corpus", type=Path, default=None,
        help="Path to corpus JSON: list of {bug_id, title, body, [expected_classification], [expected_requirement_ids]}",
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read a single bug JSON from stdin instead of a corpus file.",
    )
    parser.add_argument(
        "--threshold", type=float, default=_DEFAULT_THRESHOLD,
        help=f"Cosine similarity threshold for 'in' classification (default: {_DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--accuracy-bar", type=float, default=_DEFAULT_ACCURACY_BAR,
        help=f"Fail with exit 2 if corpus accuracy < this (default: {_DEFAULT_ACCURACY_BAR})",
    )
    parser.add_argument(
        "--project-dir", type=Path, default=None,
        help="Project root for the spec index. Default: walk up from cwd looking for .beads/.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional path to write the JSON result; default: stdout.",
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve() if args.project_dir else _resolve_project_dir()
    index = load_index(project_dir)

    # Build the bug list
    if args.corpus:
        with args.corpus.open(encoding="utf-8") as f:
            bugs = json.load(f)
        if not isinstance(bugs, list):
            sys.stderr.write("error: corpus must be a JSON list\n")
            return 1
    elif args.stdin:
        text = sys.stdin.read()
        try:
            bug = json.loads(text)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"error: stdin not valid JSON: {e}\n")
            return 1
        bugs = [bug] if isinstance(bug, dict) else bug
    else:
        sys.stderr.write("error: pass --corpus <path> or --stdin\n")
        return 1

    if not index["requirements"]:
        sys.stderr.write(
            "warning: spec index has zero requirements — every bug will classify as 'out'\n"
        )

    # Embed all bugs in one batch
    bug_embeddings = embed_bugs(bugs) if bugs else []

    results = [
        classify_bug(bug, emb, index, args.threshold)
        for bug, emb in zip(bugs, bug_embeddings)
    ]

    output: dict[str, Any] = {
        "schema_version": 1,
        "threshold": args.threshold,
        "model": _MODEL_NAME,
        "index_built_at": index.get("built_at"),
        "results": results,
    }

    # Accuracy assertion if the corpus has labels
    accuracy_info = evaluate_accuracy(results, bugs)
    if accuracy_info["accuracy"] is not None:
        output["accuracy"] = round(accuracy_info["accuracy"], 4)
        output["total"] = accuracy_info["total"]
        output["correct"] = accuracy_info["correct"]
        output["details"] = accuracy_info["details"]

    text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)

    # Riskiest-assumption check: fail if accuracy is below the bar
    if accuracy_info["accuracy"] is not None:
        if accuracy_info["accuracy"] < args.accuracy_bar:
            sys.stderr.write(
                f"\nFAIL: accuracy {accuracy_info['accuracy']:.3f} < "
                f"bar {args.accuracy_bar} ({accuracy_info['correct']}/{accuracy_info['total']})\n"
            )
            return 2
        sys.stderr.write(
            f"\nPASS: accuracy {accuracy_info['accuracy']:.3f} >= "
            f"bar {args.accuracy_bar} ({accuracy_info['correct']}/{accuracy_info['total']})\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
