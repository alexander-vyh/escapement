#!/usr/bin/env python3
"""
Helper for agents to scaffold a contract.json in the active thread directory.

Usage:
  init_contract.py --goal "..." --verify "shell command" [--expected-exit N] [--source agent-declared|bead-derived|user-authored]

Writes to $HARNESS_THREAD_DIR/contract.json (default: harness/threads/current/contract.json).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from would_block_stop import thread_dir_for_session, sanitize_session_id  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True, help="One-sentence outcome.")
    parser.add_argument("--verify", required=True, help="Shell command whose exit code is the oracle.")
    parser.add_argument("--expected-exit", type=int, default=0)
    parser.add_argument("--source", choices=["agent-declared", "bead-derived", "user-authored"], default="agent-declared")
    parser.add_argument("--thread-id", default=None)
    args = parser.parse_args(argv)

    harness_root = pathlib.Path(os.environ.get("HARNESS_ROOT", pathlib.Path.home() / "GitHub" / "claude-workflow-setup" / "harness"))
    # Resolve the per-session thread dir the same way the Stop hook and verify do,
    # so a session's contract lands where its own Stop hook will look for it.
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    thread_dir = thread_dir_for_session(session_id, harness_root)
    thread_dir.mkdir(parents=True, exist_ok=True)

    contract = {
        "goal": args.goal,
        "verification_command": args.verify,
        "expected_exit": args.expected_exit,
        "source": args.source,
        "thread_id": args.thread_id or sanitize_session_id(session_id) or f"current-{uuid.uuid4().hex[:8]}",
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "last_run": None,
    }

    out = thread_dir / "contract.json"
    with out.open("w") as f:
        json.dump(contract, f, indent=2)

    print(f"contract written to {out}")
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
