"""Repair of a primary checkout whose shared config was flipped to bare.

A stray ``GIT_DIR=.git git init --bare`` (or the same command run with ``.git``
as the working directory) writes ``core.bare = true`` into an existing
repository's shared config. Objects, refs and hooks survive untouched, but the
primary checkout stops being a work tree: ``status``, ``merge --ff-only`` and
``rev-parse --show-toplevel`` all fail. Linked worktrees keep working, because
Git ignores shared-config bareness whenever a ``commondir`` file is present, so
the damage is confined to the primary -- and therefore to every Escapement
lifecycle operation, all of which must resolve the primary first.

Detection is anchored on git-dir *layout*, never on ``core.bare`` alone: a
repository legitimately created by ``git clone --bare x.git`` and then given
linked worktrees carries ``core.bare = true`` in exactly the same place.
Writing ``false`` into that repository would make Git adopt its parent
directory as a work tree, so the bareness value alone can never authorize a
repair.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RepairOutcome = Literal["repaired", "reflipped", "contended", "denied"]

RECURRENCE_WINDOW_SECONDS = 7 * 24 * 60 * 60
RECORD_NAME = "root-health.jsonl"


class PrimaryHealthError(RuntimeError):
    """A flipped primary checkout could not be restored to a usable state."""


@dataclass(frozen=True)
class PrimaryRepair:
    """One completed repair of a primary checkout's shared config."""

    primary: Path
    common_dir: Path
    head_sha: str
    branch: str
    recurrence: int


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _config_get(config: Path, key: str) -> str | None:
    if not config.is_file():
        return None
    result = subprocess.run(
        ("git", "config", "--file", str(config), "--get", key),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.strip()


def _common_dir(requested: Path) -> Path | None:
    """Resolve the shared git directory using a command that survives bareness."""
    result = _git(
        requested, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def _is_flipped_primary(common: Path) -> bool:
    """Report whether ``common`` is a checkout's own .git wrongly marked bare.

    Every clause excludes a legitimate configuration: a bare repository is not
    named ``.git`` and holds no index; ``--separate-git-dir`` and submodule
    git-dirs fail the name test; an intentional per-worktree or work-tree
    override means the value was placed deliberately.
    """
    if common.name != ".git" or common.is_symlink() or not common.is_dir():
        return False
    if not (common / "index").is_file():
        return False
    config = common / "config"
    if _config_get(config, "core.bare") != "true":
        return False
    if _config_get(config, "core.worktree") is not None:
        return False
    if _config_get(common / "config.worktree", "core.bare") is not None:
        return False
    # The primary must actually be unusable; anything else is not this fault.
    return _git(common.parent, "rev-parse", "--show-toplevel").returncode != 0


def _record_path(primary: Path, common: Path) -> Path:
    beads = primary / ".beads"
    if beads.is_dir():
        return beads / RECORD_NAME
    return common / f"escapement-{RECORD_NAME}"


def _prior_repairs(record: Path, now: float) -> int:
    if not record.is_file():
        return 0
    count = 0
    for line in record.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        detected = entry.get("detected_at")
        if isinstance(detected, (int, float)) and now - detected <= (
            RECURRENCE_WINDOW_SECONDS
        ):
            count += 1
    return count


def _write_record(record: Path, entry: dict[str, object]) -> None:
    record.parent.mkdir(parents=True, exist_ok=True)
    with record.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def repair_flipped_primary(requested: Path) -> PrimaryRepair | None:
    """Restore a primary checkout that a stray bare init made unusable.

    Returns ``None`` when the repository is not in that specific state, so the
    caller's original error surfaces untouched. Raises
    :class:`PrimaryHealthError` when the repair is owed but cannot be completed
    and verified, because continuing would hide an unusable shared repository.
    """
    common = _common_dir(requested)
    if common is None or not _is_flipped_primary(common):
        return None

    primary = common.parent
    config = common / "config"
    now = time.time()
    # Evidence is captured before the write: the mtime and the exact bytes are
    # the only forensic trace of a writer nobody has identified yet.
    previous = config.read_text(encoding="utf-8")
    head = _git(common, "--git-dir", str(common), "rev-parse", "--verify", "HEAD^{commit}")
    branch = _git(common, "--git-dir", str(common), "symbolic-ref", "--quiet", "--short", "HEAD")
    head_sha = head.stdout.strip()
    branch_name = branch.stdout.strip()
    record = _record_path(primary, common)
    entry: dict[str, object] = {
        "detected_at": now,
        "primary": str(primary),
        "common_dir": str(common),
        "config_mtime": config.stat().st_mtime,
        "config_sha256": hashlib.sha256(previous.encode("utf-8")).hexdigest(),
        "config_before": previous,
        "head_sha": head_sha,
        "branch": branch_name,
        "recurrence": _prior_repairs(record, now) + 1,
    }

    repair = subprocess.run(
        ("git", "config", "--file", str(config), "core.bare", "false"),
        capture_output=True,
        text=True,
        check=False,
    )
    if repair.returncode:
        stderr = repair.stderr.strip()
        outcome: RepairOutcome = (
            "contended" if "could not lock" in stderr.lower() else "denied"
        )
        entry["outcome"] = outcome
        entry["error"] = stderr
        _write_record(record, entry)
        raise PrimaryHealthError(
            f"primary checkout is bare and could not be repaired ({outcome}): {stderr}"
        )

    # A writer that is still live will undo the repair; repairing again would
    # only trade writes with it, so report instead of looping.
    if _config_get(config, "core.bare") == "true":
        entry["outcome"] = "reflipped"
        _write_record(record, entry)
        raise PrimaryHealthError(
            "primary checkout was marked bare again immediately after repair; "
            f"a live writer is active on {config}"
        )

    toplevel = _git(primary, "rev-parse", "--show-toplevel")
    observed_common = _common_dir(primary)
    observed_head = _git(primary, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    observed_branch = _git(primary, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    status = _git(primary, "status", "--porcelain=v1")
    if (
        toplevel.returncode
        or Path(toplevel.stdout.strip()).resolve() != primary
        or observed_common != common
        or observed_head != head_sha
        or observed_branch != branch_name
        or status.returncode
    ):
        entry["outcome"] = "denied"
        entry["error"] = "postcondition failed"
        _write_record(record, entry)
        raise PrimaryHealthError(
            f"primary checkout bare-repair postcondition failed: {primary}"
        )

    entry["outcome"] = "repaired"
    _write_record(record, entry)
    recurrence = int(entry["recurrence"])
    detail = (
        f"escapement: repaired primary checkout {primary} "
        f"(core.bare was true; evidence in {record})"
    )
    if recurrence > 1:
        detail += (
            f" -- occurrence {recurrence} in the last 7 days;"
            " an unidentified writer keeps marking this repository bare"
        )
    print(detail, file=sys.stderr)
    return PrimaryRepair(
        primary=primary,
        common_dir=common,
        head_sha=head_sha,
        branch=branch_name,
        recurrence=recurrence,
    )
