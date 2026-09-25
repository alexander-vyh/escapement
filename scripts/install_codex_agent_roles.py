#!/usr/bin/env python3
"""Install Escapement's Codex agent roles without clobbering other owners' files.

Codex plugins cannot ship agent roles, so the updater copies the plugin's
``agents/*.toml`` into the user's Codex agents directory.  A provenance record
(``.escapement-owned.json``: filename -> sha256 of what Escapement last wrote)
decides who owns an existing file:

* absent target            -> install
* identical target         -> no-op (recorded as Escapement-owned)
* recorded, unmodified     -> replace
* anything else            -> move aside to ``<name>.pre-escapement-<UTC>``,
                              then install; the backup path is printed

Nothing is ever deleted without a backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


RECORD_NAME = ".escapement-owned.json"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.escapement-{os.getpid()}")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_record(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"FATAL: unreadable Escapement agent record {path}: {error}")
    if not isinstance(record, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in record.items()
    ):
        raise SystemExit(f"FATAL: malformed Escapement agent record {path}")
    return record


def install(source_dir: Path, agents_dir: Path) -> int:
    sources = sorted(source_dir.glob("*.toml")) if source_dir.is_dir() else []
    if not sources:
        print(f"no Codex agent roles to install from {source_dir}")
        return 0
    agents_dir.mkdir(parents=True, exist_ok=True)
    record_path = agents_dir / RECORD_NAME
    record = _load_record(record_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    for source in sources:
        content = source.read_bytes()
        digest = _sha256(content)
        target = agents_dir / source.name
        if target.is_symlink() or target.exists():
            if not target.is_symlink() and target.is_file() and target.read_bytes() == content:
                record[source.name] = digest
                print(f"agent role already current: {target}")
                continue
            owned = (
                not target.is_symlink()
                and target.is_file()
                and record.get(source.name) == _sha256(target.read_bytes())
            )
            if not owned:
                backup = target.with_name(f"{target.name}.pre-escapement-{timestamp}")
                if backup.exists() or backup.is_symlink():
                    raise SystemExit(f"FATAL: agent role backup already exists: {backup}")
                os.replace(target, backup)
                print(f"moved non-Escapement agent role aside; backup: {backup}")
        _atomic_write(target, content)
        record[source.name] = digest
        print(f"installed agent role: {target}")

    _atomic_write(
        record_path,
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Escapement Codex agent roles.")
    parser.add_argument("source_dir", type=Path, help="installed plugin agents/ directory")
    parser.add_argument("agents_dir", type=Path, help="Codex agents directory")
    args = parser.parse_args()
    return install(args.source_dir, args.agents_dir)


if __name__ == "__main__":
    raise SystemExit(main())
