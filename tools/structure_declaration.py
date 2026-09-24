#!/usr/bin/env python3
"""What a human decided about a repository's structure.

This is the *intent* half of "store intent, derive measurement". Scope,
exclusions, pins and waivers are decisions somebody made and must be able to
defend, so they are stored, versioned and reviewed. Measured values are
observations and are never stored here.

The load-bearing distinction is between a pin and a waiver, which point in
opposite directions:

    pin     an obligation  -- this artifact must BECOME something
    waiver  a permission   -- this artifact may STAY as it is

Measured across this estate over four months, growth in waiver surfaces tracked
degrading outcomes (93 of 122 waived files were created *after* the gate that
waived them existed; in one repository 28 of 28) while growth in the pin surface
tracked improving ones (62 -> 81 pins while the worst file fell 36% and
per-file complexity fell 44%). A consumer that counts "declarations" without
distinguishing the two produces a number whose sign is meaningless.

So they are different record types with different required fields. A waiver
without an expiry is not a waiver, and a pin without a target is not a pin.
Conflating them is unrepresentable rather than discouraged.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib

DECLARATION_PATH = ".escapement/structure.json"

PIN_REQUIRED = ("path", "target", "owner", "created")
# An unreplaced marker means nobody has looked yet. Bootstrap can propose a
# scope but it cannot forecast where the next defect will be, so the file it
# writes is deliberately born invalid.
REVIEW_MARKER = "REVIEW"
WAIVER_REQUIRED = ("path", "reason", "owner", "expires")
# A field that belongs to exactly one record type. Its presence on the other is
# the conflation this schema exists to prevent, so it is an error and not a
# warning: the two records predict opposite futures.
PIN_ONLY = ("target",)
WAIVER_ONLY = ("reason", "expires")


def is_artifact_echo(text: str, subject: str) -> bool:
    """True when a justification merely restates what the tool already knew.

    Mirrors Rule 3 of the file-complexity gate deliberately rather than by
    accident: that gate recorded a filesystem path in its reason field 1,419
    times out of 1,419, so every presence check passed while the corpus held no
    argument at all. The duplication is intentional — the gate ships in four
    standalone copies and cannot import this module — and
    `test_echo_rule_agrees_with_the_gate` pins the two implementations to one
    another so they cannot drift apart silently.
    """
    value = (text or "").strip()
    if not value:
        return True
    normalised = value.replace(os.sep, "/")
    target = (subject or "").replace(os.sep, "/")
    if target and normalised in (target, os.path.basename(target)):
        return True
    return "/" in normalised and len(normalised.split()) == 1


@dataclasses.dataclass
class Pin:
    """An obligation: this artifact must become something it is not yet."""

    path: str
    target: dict
    owner: str
    created: str
    note: str = ""


@dataclasses.dataclass
class Waiver:
    """A permission: this artifact may stay as it is, until a named date."""

    path: str
    reason: str
    owner: str
    expires: str
    note: str = ""


@dataclasses.dataclass
class Declaration:
    scope: list[str] = dataclasses.field(default_factory=list)
    exclusions: list[dict] = dataclasses.field(default_factory=list)
    pins: list[Pin] = dataclasses.field(default_factory=list)
    waivers: list[Waiver] = dataclasses.field(default_factory=list)
    problems: list[str] = dataclasses.field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def _check_record(raw: dict, index: int, kind: str) -> list[str]:
    required = PIN_REQUIRED if kind == "pin" else WAIVER_REQUIRED
    foreign = WAIVER_ONLY if kind == "pin" else PIN_ONLY
    problems = []
    for field in required:
        if not raw.get(field):
            problems.append(f"{kind}[{index}]: missing required field {field!r}")
    for field in foreign:
        if field in raw:
            problems.append(
                f"{kind}[{index}]: carries {field!r}, which belongs to the other "
                f"record type. A pin is an obligation and a waiver is a permission; "
                f"a record cannot be both."
            )
    return problems


def parse(data: dict) -> Declaration:
    """Read a declaration, reporting every problem rather than the first."""
    decl = Declaration(scope=list(data.get("scope") or []))

    for index, raw in enumerate(data.get("exclusions") or []):
        if not isinstance(raw, dict):
            decl.problems.append(f"exclusion[{index}]: must be an object with a reason")
            continue
        decl.exclusions.append(raw)
        path = raw.get("path", "")
        why = raw.get("why", "")
        if not path:
            decl.problems.append(f"exclusion[{index}]: missing 'path'")
        if is_artifact_echo(why, path):
            decl.problems.append(
                f"exclusion[{index}] ({path or '?'}): 'why' restates the path instead "
                f"of forecasting what goes wrong here. An exclusion is a prediction "
                f"about where the next defect will be."
            )
        elif REVIEW_MARKER in why.upper() or REVIEW_MARKER in path.upper():
            decl.problems.append(
                f"exclusion[{index}] ({path or '?'}): still carries a {REVIEW_MARKER} "
                f"marker. A generated skeleton must not be mistakable for a "
                f"considered decision."
            )

    for index, raw in enumerate(data.get("pins") or []):
        problems = _check_record(raw, index, "pin")
        decl.problems.extend(problems)
        if not problems:
            decl.pins.append(Pin(
                path=raw["path"], target=raw["target"], owner=raw["owner"],
                created=raw["created"], note=raw.get("note", ""),
            ))

    for index, raw in enumerate(data.get("waivers") or []):
        problems = _check_record(raw, index, "waiver")
        if not problems and is_artifact_echo(raw.get("reason", ""), raw.get("path", "")):
            problems.append(
                f"waiver[{index}] ({raw.get('path')}): 'reason' restates the artifact. "
                f"A path is not an argument."
            )
        decl.problems.extend(problems)
        if not problems:
            decl.waivers.append(Waiver(
                path=raw["path"], reason=raw["reason"], owner=raw["owner"],
                expires=raw["expires"], note=raw.get("note", ""),
            ))

    return decl


def load(repo: str | pathlib.Path) -> Declaration | None:
    path = pathlib.Path(repo) / DECLARATION_PATH
    if not path.exists():
        return None
    try:
        return parse(json.loads(path.read_text()))
    except json.JSONDecodeError as exc:
        decl = Declaration()
        decl.problems.append(f"{DECLARATION_PATH}: invalid JSON — {exc}")
        return decl


def expired(decl: Declaration, today: str) -> list[Waiver]:
    """Waivers past their date. An unexpiring waiver is a silent policy change."""
    return [w for w in decl.waivers if w.expires < today]


def render(decl: Declaration, today: str = "") -> str:
    """Report pins and waivers separately, always. Never one 'declarations' count."""
    lines = [
        f"scope       {len(decl.scope)} pattern(s): {', '.join(decl.scope) or '(none)'}",
        f"exclusions  {len(decl.exclusions)}",
        f"pins        {len(decl.pins)}   obligations — artifacts that must change",
        f"waivers     {len(decl.waivers)}   permissions — artifacts that may not",
    ]
    if today:
        stale = expired(decl, today)
        if stale:
            lines.append(f"  EXPIRED   {len(stale)}: " + ", ".join(w.path for w in stale))
    if decl.problems:
        lines.append("")
        lines.append(f"{len(decl.problems)} problem(s):")
        lines += [f"  - {p}" for p in decl.problems]
    else:
        lines.append("")
        lines.append("declaration is well formed")
    return "\n".join(lines)
