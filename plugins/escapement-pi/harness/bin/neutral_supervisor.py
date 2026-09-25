#!/usr/bin/env python3
"""Durable continuation bridge for actions that remain unresolved."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from neutral_adapters import NativeResult, NeutralAdapter
from neutral_contract import NeutralDecision, PendingAction


class SupervisorError(RuntimeError):
    """Durable continuation state cannot be read or written safely."""


class LifecycleBridge:
    """Persist pending neutral actions and resume through a registered adapter."""

    filename = "pending-actions.json"
    completed_filename = "completed-actions.json"

    def __init__(self, state_root: str | os.PathLike[str]) -> None:
        self.state_root = Path(state_root)
        self.state_path = self.state_root / self.filename
        self.completed_path = self.state_root / self.completed_filename

    def _load_path(self, path: Path, label: str) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SupervisorError(f"cannot load {label}: {path}") from error
        if not isinstance(raw, dict) or any(not isinstance(value, dict) for value in raw.values()):
            raise SupervisorError(f"{label} state must be an object of objects")
        return raw

    def _load(self) -> dict[str, dict[str, Any]]:
        return self._load_path(self.state_path, "pending actions")

    def _write_path(self, path: Path, entries: dict[str, dict[str, Any]]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", dir=self.state_root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entries, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            directory = os.open(self.state_root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise SupervisorError(f"cannot persist lifecycle state: {path}") from error

    def _write(self, entries: dict[str, dict[str, Any]]) -> None:
        self._write_path(self.state_path, entries)

    def persist(self, decision: NeutralDecision) -> bool:
        """Store only a runtime-issued pending action; immediate results stay inline."""
        pending = decision.pending_action
        if pending is None:
            return False
        entries = self._load()
        entries[pending.request_id] = pending.to_dict()
        self._write(entries)
        return True

    def pending(self, request_id: str) -> PendingAction:
        try:
            raw = self._load()[request_id]
        except KeyError as error:
            raise SupervisorError(f"unknown pending action: {request_id}") from error
        try:
            return PendingAction(**{key: raw[key] for key in PendingAction.__dataclass_fields__})
        except (KeyError, TypeError, ValueError) as error:
            raise SupervisorError(f"invalid pending action: {request_id}") from error

    def pending_count(self) -> int:
        return len(self._load())

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self._load()

    def completed_snapshot(self) -> dict[str, dict[str, Any]]:
        return self._load_path(self.completed_path, "completed actions")

    def resume(self, request_id: str, adapter: NeutralAdapter) -> NativeResult:
        """Resume through the adapter; do not re-evaluate policy at the bridge."""
        pending = self.pending(request_id)
        result = adapter.resume(pending)
        entries = self._load()
        if result.state_transition == "outcome-resumed" and result.executed:
            completed = self._load_path(self.completed_path, "completed actions")
            completed[request_id] = {
                "pending": pending.to_dict(),
                "result": result.to_dict(),
            }
            self._write_path(self.completed_path, completed)
            entries.pop(request_id, None)
        else:
            updated = pending.to_dict()
            updated["status"] = "advisory"
            entries[request_id] = updated
        self._write(entries)
        return result
