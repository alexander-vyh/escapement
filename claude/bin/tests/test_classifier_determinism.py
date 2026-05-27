#!/usr/bin/env python3
"""Task 2.3 from openspec-beads-staleness/tasks.md: classifier determinism.

Runs `classify_bugs.py` twice in succession on the same corpus and asserts
the two outputs are byte-identical. This is the deterministic-output
scenario from spec-area-classifier.md:

    Given the same input → same output, every time
    (`normalize_embeddings=True` makes cosine similarity reproducible)

## Usage

    python3 claude/bin/tests/test_classifier_determinism.py

Exits 0 on success, 1 on byte mismatch.
"""

from __future__ import annotations

import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


_CORPUS = [
    {
        "bug_id": "det-1",
        "title": "discovery gate denies all feature creation",
        "body": "the bd create --type=feature path is broken; gate looks in wrong directory",
    },
    {
        "bug_id": "det-2",
        "title": "unrelated CSS adjustment",
        "body": "just tweaking the primary button hover color",
    },
    {
        "bug_id": "det-3",
        "title": "signal log never persists across sessions",
        "body": "gate signal records evaporate; need durable store",
    },
]


def run_classifier(corpus_path: Path, project_dir: Path) -> str:
    """Invoke classify_bugs.py and return stdout."""
    script = Path(__file__).resolve().parent.parent / "classify_bugs.py"
    result = subprocess.run(
        [
            "uv", "run", str(script),
            "--corpus", str(corpus_path),
            "--threshold", "0.3",
            "--project-dir", str(project_dir),
            "--accuracy-bar", "0.0",  # don't fail on accuracy in this test
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 2):
        sys.stderr.write(
            f"classify_bugs.py exited unexpectedly ({result.returncode})\n"
            f"stderr:\n{result.stderr}\n"
        )
        sys.exit(1)
    return result.stdout


def main() -> int:
    # Find the project root via .beads/
    import os
    cwd = Path(os.getcwd()).resolve()
    project_dir: Path | None = None
    for parent in [cwd, *cwd.parents]:
        if (parent / ".beads" / ".spec-index.json").is_file():
            project_dir = parent
            break
    if project_dir is None:
        sys.stderr.write(
            "error: no .beads/.spec-index.json found from cwd. "
            "Run claude/bin/spec_index_build.py first.\n"
        )
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        corpus_path = Path(tmp) / "corpus.json"
        corpus_path.write_text(
            json.dumps(_CORPUS, ensure_ascii=False),
            encoding="utf-8",
        )

        output_1 = run_classifier(corpus_path, project_dir)
        output_2 = run_classifier(corpus_path, project_dir)

        if output_1 == output_2:
            print(
                f"PASS: classifier output is deterministic "
                f"({len(output_1)} bytes, identical across two runs)"
            )
            return 0

        # Show a diff to make the failure debuggable
        sys.stderr.write("FAIL: classifier output differs between runs\n\n")
        diff = difflib.unified_diff(
            output_1.splitlines(keepends=True),
            output_2.splitlines(keepends=True),
            fromfile="run 1",
            tofile="run 2",
            n=2,
        )
        sys.stderr.writelines(diff)
        return 1


if __name__ == "__main__":
    sys.exit(main())
