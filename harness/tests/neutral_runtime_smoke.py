#!/usr/bin/env python3
"""Executable proof for the neutral Pi/Codex/Claude walking skeleton."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

from neutral_oracle import run_fixture_suite  # noqa: E402


def main() -> int:
    report = run_fixture_suite()
    print(
        json.dumps(
            {
                "capability_id": report["capability_id"],
                "clients": sorted(report["clients"]),
                "negative_controls": report["negative_controls"],
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
