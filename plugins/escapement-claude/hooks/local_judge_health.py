#!/usr/bin/env python3
"""Health probe for Escapement's local semantic judge service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    import _local_judge_client as _lj
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "reason": f"import_error:{exc}"}))
    raise SystemExit(1)


def main() -> int:
    result = _lj.health_check()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
