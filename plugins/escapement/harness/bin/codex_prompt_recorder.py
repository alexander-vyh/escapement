#!/usr/bin/env python3
"""
Codex UserPromptSubmit recorder — persists the user's latest prompt into the
session's thread dir so codex_stop_hook.py can evaluate user release
("stop", "done for now", ...) without parsing Codex transcript files
(nullable path, undocumented format).

Fail-open: any error exits 0 silently — recording is an enabling convenience;
its absence degrades the release path, never the session.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys

from would_block_stop import thread_dir_for_session


def _harness_root() -> pathlib.Path:
    from would_block_stop import DEFAULT_HARNESS_ROOT

    return pathlib.Path(os.environ.get("HARNESS_ROOT", DEFAULT_HARNESS_ROOT))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return 0
        session_id = payload.get("session_id") or "codex-unknown"
        thread_dir = thread_dir_for_session(session_id, _harness_root())
        thread_dir.mkdir(parents=True, exist_ok=True)
        (thread_dir / "last_user_message.json").write_text(
            json.dumps({
                "text": prompt,
                "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            })
        )
    except Exception:  # noqa: BLE001 — fail-open; recording is best-effort
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
