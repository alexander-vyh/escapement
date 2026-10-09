#!/usr/bin/env python3
"""Opt-in physical-tool inspection admission, with an always-available report lane.

The host supplies the actual parent session file and external-input provenance.
No executor body is parsed, and no agent-invokable reset or waiver is provided.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from _gate_signal import record as record_signal
from _host_output import deny

HEADER_BYTES = 16384
STATE_BYTES = 256 * 1024
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
# Only read's documented finite line selectors are decoded; opaque URIs and
# archive/database/query selectors do not acquire implicit access.
LINE_SELECTOR = re.compile(r"(?:[1-9][0-9]*(?:-[1-9][0-9]*|\+[1-9][0-9]*)?|-[1-9][0-9]*)(?:,(?:[1-9][0-9]*(?:-[1-9][0-9]*|\+[1-9][0-9]*)?|-[1-9][0-9]*))*\Z")
WRITERS = {
    "write": "path", "Write": "file_path",
    "edit": "path", "Edit": "file_path",
    "mcp__serena_replace_content": "relative_path",
    "mcp__escapement_serena_replace_content": "relative_path",
    "mcp__serena_replace_symbol_body": "relative_path",
    "mcp__escapement_serena_replace_symbol_body": "relative_path",
    "mcp__serena_insert_after_symbol": "relative_path",
    "mcp__escapement_serena_insert_after_symbol": "relative_path",
    "mcp__serena_insert_before_symbol": "relative_path",
    "mcp__escapement_serena_insert_before_symbol": "relative_path",
}


def state_directory() -> Path:
    return Path(os.environ.get("ESCAPEMENT_INSPECTION_STATE_DIR",
                               "~/.local/state/escapement/inspections")).expanduser().resolve()


def safe_session(value: object) -> str:
    if not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        raise ValueError("session ID must be a safe, nonempty filename")
    return value


@contextmanager
def locked_state():
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save(path: Path, value: dict) -> None:
    encoded = json.dumps(value) + "\n"
    if len(encoded.encode("utf-8")) > STATE_BYTES:
        raise ValueError("inspection state exceeds 256 KiB bound")
    fd, temporary = tempfile.mkstemp(prefix=".inspection-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(directory: Path, session: str) -> dict | None:
    path = directory / f"{session}.json"
    if not path.exists():
        return None
    with path.open("rb") as stream:
        encoded = stream.read(STATE_BYTES + 1)
    if len(encoded) > STATE_BYTES:
        raise ValueError("inspection state exceeds 256 KiB bound")
    value = json.loads(encoded)
    if (not isinstance(value, dict) or value.get("version") != 1
            or value.get("session_id") != session
            or value.get("phase") not in {"active", "report", "released"}
            or not isinstance(value.get("sources"), list)
            or not isinstance(value.get("artifacts"), list)
            or not isinstance(value.get("seen_calls"), list)
            or type(value.get("max_actions")) is not int
            or not 1 <= value["max_actions"] <= 48
            or type(value.get("admitted")) is not int
            or type(value.get("rejected")) is not int
            or value["admitted"] < 0 or value["rejected"] < 0
            or not all(isinstance(p, str) and Path(p).is_absolute()
                       for p in value["sources"] + value["artifacts"])):
        raise ValueError("invalid inspection state; report unknown findings and handoff for state repair")
    value.setdefault("report_writes", {})
    if (not value["sources"] or len(value["sources"]) > 32
            or not value["artifacts"] or len(value["artifacts"]) > 4
            or not isinstance(value["report_writes"], dict)
            or any(p not in value["artifacts"] or type(n) is not int or not 0 <= n <= 2
                   for p, n in value["report_writes"].items())):
        raise ValueError("invalid finite report/source scope")
    return value


def signal(decision: str, reason: str, session: str) -> None:
    if not record_signal("inspection_boundary", decision, reason, session_id=session):
        print("inspection_boundary: persistent gate signal could not be written", file=sys.stderr)


def parent_session(path: object) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("missing parent session binding")
    with Path(path).open("rb") as stream:
        line = stream.readline(HEADER_BYTES + 1)
    if len(line) > HEADER_BYTES:
        raise ValueError("parent session header exceeds bounded first-header limit")
    header = json.loads(line)
    if not isinstance(header, dict) or header.get("type") != "session":
        raise ValueError("parent binding must resolve to a first JSON session header")
    return safe_session(header.get("id"))


def bound_record(directory: Path, payload: dict) -> dict | None:
    session = safe_session(payload.get("session_id"))
    own = load(directory, session)
    if payload.get("parent_session") is not None:
        parent = parent_session(payload["parent_session"])
        inherited = load(directory, parent)
        if inherited is not None and inherited["phase"] != "released":
            return inherited
    return own


def canonical_input(value: object, cwd: str, *, selectors: bool = False) -> str:
    if not isinstance(value, str) or not value or "://" in value:
        raise ValueError("path must be an explicit local nominated path")
    if selectors and ":" in value:
        path, suffix = value.split(":", 1)
        if not LINE_SELECTOR.fullmatch(suffix):
            raise ValueError("only bounded line selectors are permitted")
        value = path
    if any(char in value for char in "*?[]"):
        raise ValueError("recursive scans and wildcard paths are prohibited")
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else Path(cwd) / path).resolve())


def report_reason(scope: dict, detail: str) -> str:
    destinations = ", ".join(scope["artifacts"])
    return (f"Inspection boundary: {detail}. Write/edit the exact report destinations: "
            f"{destinations}. Report missing comparisons as unknown; a substantive final "
            "answer or handoff is also possible. Do not retry prohibited actions; "
            "the second rejection aborts this inspection turn. No reset, renewal, or waiver.")


def reject(directory: Path, scope: dict, detail: str) -> dict:
    reason = report_reason(scope, detail)
    if scope["phase"] != "report":
        scope["phase"] = "report"
        signal("report", reason, scope["session_id"])
    scope["rejected"] += 1
    save(directory / f"{scope['session_id']}.json", scope)
    signal("deny", reason, scope["session_id"])
    output = deny(reason)
    if scope["rejected"] >= 2:
        output["hookSpecificOutput"]["inspectionAbort"] = True
    return output


def release(directory: Path, scope: dict | None, source: str) -> None:
    if source not in {"interactive", "rpc"}:
        raise ValueError("only genuine host external input with source interactive/rpc releases inspection")
    if scope is not None and scope["phase"] != "released":
        scope["phase"] = "released"
        save(directory / f"{scope['session_id']}.json", scope)
        signal("released", f"Host external input: {source}; historical scope retained", scope["session_id"])


def hook(payload: dict) -> dict:
    session = safe_session(payload.get("session_id"))
    with locked_state() as directory:
        try:
            scope = bound_record(directory, payload)
        except (OSError, ValueError, TypeError) as error:
            # An unreadable explicit binding is never a fresh child allowance.
            # This rejection-only counter grants no tool access or scope.
            counter = directory / f".unbound-{session}.rejects"
            count = int(counter.read_text()) + 1 if counter.exists() else 1
            counter.write_text(str(count), encoding="utf-8")
            reason = (f"Inspection parent/state binding unavailable: {error}. Do not execute "
                      "or create fresh inspection allowance. Report missing comparisons as "
                      "unknown in a substantive final answer and handoff to the parent "
                      "using its nominated report destinations; binding repair is host-owned.")
            signal("deny", reason, session)
            output = deny(reason)
            if count >= 2:
                output["hookSpecificOutput"]["inspectionAbort"] = True
            return output
        if payload.get("hook_event_name") == "ExternalInput":
            if payload.get("input_source") in {"interactive", "rpc"}:
                release(directory, scope, payload["input_source"])
            return {}
        if scope is None or scope["phase"] == "released":
            return {}
        if payload.get("hook_event_name") == "Stop":
            return {"hookSpecificOutput": {"hookEventName": "Stop", "inspectionHandoff": True}}
        tool = payload.get("tool_name")
        inputs = payload.get("tool_input")
        if not isinstance(inputs, dict):
            return reject(directory, scope, "tool input is not a local path request")
        cwd = payload.get("cwd") or os.getcwd()
        writer = tool in WRITERS
        try:
            if writer:
                path = canonical_input(inputs.get(WRITERS[tool]), cwd)
                if path not in scope["artifacts"]:
                    return reject(directory, scope, "writer is outside exact nominated report destinations")
            elif tool in {"read", "Read"}:
                if inputs.get("recursive"):
                    return reject(directory, scope, "recursive directory reads are prohibited")
                field = "path" if tool == "read" else "file_path"
                path = canonical_input(inputs.get(field), cwd, selectors=True)
                if path not in scope["sources"] and path not in scope["artifacts"]:
                    return reject(directory, scope, "read is outside exact nominated sources/reports")
                if scope["phase"] == "report" and path not in scope["artifacts"]:
                    return reject(directory, scope, "inspection is report-only after rejection/exhaustion")
            else:
                return reject(directory, scope, f"physical tool {tool!r} is prohibited (execution, opaque tools, and delegation are not inspection reads)")
        except (OSError, ValueError, TypeError) as error:
            return reject(directory, scope, str(error))
        call_id = payload.get("tool_use_id")
        key = f"{session}:{call_id}" if isinstance(call_id, str) and call_id else None
        if key is not None and key in scope["seen_calls"]:
            return {}
        if writer:
            writes = scope["report_writes"].get(path, 0)
            if writes >= 2:
                output = reject(directory, scope, "two physical report mutations already admitted for this artifact; finish with a final answer/handoff")
                output["hookSpecificOutput"]["inspectionAbort"] = True
                return output
            scope["report_writes"][path] = writes + 1
            if scope["phase"] == "report":
                if key is not None:
                    scope["seen_calls"].append(key)
                save(directory / f"{scope['session_id']}.json", scope)
                return {}
        if scope["admitted"] >= scope["max_actions"]:
            if not writer:
                return reject(directory, scope, "shared physical-call allowance exhausted")
            scope["phase"] = "report"
            signal("report", report_reason(scope, "shared allowance exhausted; report writer admitted"), scope["session_id"])
        else:
            scope["admitted"] += 1
        if key is not None:
            scope["seen_calls"].append(key)
        save(directory / f"{scope['session_id']}.json", scope)
        return {}


def begin(args: argparse.Namespace, directory: Path) -> dict:
    session = safe_session(args.session)
    if load(directory, session) is not None:
        raise ValueError("inspection history already exists; renewal is prohibited")
    if (not args.source or len(args.source) > 32 or not args.artifact
            or len(args.artifact) > 4 or not 1 <= args.max_actions <= 48):
        raise ValueError("require 1..32 sources, 1..4 artifacts and 1 <= max-actions <= 48")
    sources = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in args.source))
    for source in sources:
        path = Path(source)
        if not (path.is_file() or path.is_dir()) or not os.access(path, os.R_OK):
            raise ValueError(f"source is not real/readable: {source}")
    artifacts = list(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in args.artifact))
    for artifact in artifacts:
        path = Path(artifact)
        if (artifact in sources or path == directory or directory in path.parents):
            raise ValueError("artifacts cannot alias sources or inspection state")
        if not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
            raise ValueError(f"artifact parent must exist and be writable: {artifact}")
        if path.exists():
            raise ValueError(f"artifact already exists; refusing to overwrite: {artifact}")
    created = []
    try:
        for artifact in artifacts:
            with Path(artifact).open("x", encoding="utf-8"):
                created.append(Path(artifact))
        scope = dict(version=1, session_id=session, phase="active", sources=sources,
                     artifacts=artifacts, max_actions=args.max_actions, admitted=0,
                     seen_calls=[], rejected=0, report_writes={})
        save(directory / f"{session}.json", scope)
    except Exception:
        for path in created:
            path.unlink()
        raise
    signal("active", report_reason(scope, "explicit bounded inspection started"), session)
    return scope


def main() -> None:
    if len(sys.argv) == 1:
        try:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("hook input must be a JSON object")
            output = hook(payload)
        except (OSError, ValueError, TypeError) as error:
            reason = f"Inspection input/state unavailable: {error}. Report unknown comparisons in a final answer and handoff for host binding repair."
            signal("deny", reason, "unknown")
            output = deny(reason)
        print(json.dumps(output))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("begin")
    start.add_argument("--session", required=True)
    start.add_argument("--source", action="append", required=True)
    start.add_argument("--artifact", action="append", required=True)
    start.add_argument("--max-actions", type=int, default=24)
    show = commands.add_parser("show")
    show.add_argument("--session", required=True)
    external = commands.add_parser("external-input")
    external.add_argument("--session", required=True)
    external.add_argument("--source", choices=["interactive", "rpc"], required=True)
    args = parser.parse_args()
    try:
        session = safe_session(args.session)
        with locked_state() as directory:
            if args.command == "begin":
                result = begin(args, directory)
            else:
                result = load(directory, session)
                if args.command == "external-input":
                    release(directory, result, args.source)
                elif result is None:
                    raise ValueError("no inspection record for this session")
        print(json.dumps(result))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"inspection_boundary: {error}\n")


if __name__ == "__main__":
    main()
