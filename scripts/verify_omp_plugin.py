#!/usr/bin/env python3
"""Refresh via OMP's public CLI and prove actual installed bytes and behavior."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROBE = """
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
extension({ on(event, handler) { handlers.set(event, handler); },
            sendMessage() {}, sendUserMessage() {} });
const outcomes = [];
for (const call of JSON.parse(process.argv[3])) {
  const context = { cwd: call.cwd, signal: new AbortController().signal,
    sessionManager: { getSessionId() { return "omp-deployment-probe"; },
                      getBranch() { return []; } }, ui: { notify() {} } };
  const result = await handlers.get("tool_call")(
    { type: "tool_call", toolCallId: "probe", toolName: "write",
      input: { path: call.path, content: "Deployment probe.\\n" } }, context);
  outcomes.push(result ?? null);
}
console.log(JSON.stringify(outcomes));
"""


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def registration(plugins: Path) -> tuple[Path, dict, dict]:
    manifest = read_object(plugins / "package.json")
    spec = manifest.get("dependencies", {}).get("escapement")
    if not isinstance(spec, str) or not spec:
        raise ValueError(f"OMP Escapement dependency is not registered in {plugins / 'package.json'}")
    package = plugins / "node_modules/escapement"
    metadata = read_object(package / "package.json")
    if metadata.get("name") != "escapement":
        raise ValueError(f"wrong OMP package authority: {package}")
    runtime = read_object(plugins / "omp-plugins.lock.json")
    if not isinstance(runtime.get("plugins", {}).get("escapement"), dict):
        raise ValueError("OMP Escapement runtime registration is missing")
    return package, manifest, runtime


def settings_without_version(runtime: dict) -> dict:
    # OMP updates version metadata while preserving enablement/features/settings.
    settings = copy.deepcopy(runtime)
    settings["plugins"]["escapement"].pop("version", None)
    return settings


def unrelated_plugin_data(plugins: Path, manifest: dict) -> dict[str, str]:
    """OMP's targeted upgrade must preserve other registered plugins' data."""
    snapshot = {}
    for name in manifest.get("dependencies", {}):
        if name == "escapement":
            continue
        package = plugins / "node_modules" / name
        for path in (package, *package.rglob("*")):
            relative = str(path.relative_to(plugins))
            if path.is_symlink():
                snapshot[relative] = "link:" + os.readlink(path)
            elif path.is_file():
                with path.open("rb") as stream:
                    snapshot[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
            elif path.is_dir():
                snapshot[relative] = "directory"
    return snapshot


def shipped_files(root: Path) -> set[Path]:
    files = {Path("package.json")}
    for relative in ("plugins/escapement-pi", ".agents/skills"):
        directory = root / relative
        if not directory.is_dir():
            raise ValueError(f"shipped OMP surface is missing: {directory}")
        files.update(path.relative_to(root) for path in directory.rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and path.suffix != ".pyc" and path.name != ".DS_Store")
    return files


def verify_bytes(source: Path, package: Path) -> int:
    expected = shipped_files(source)
    actual = shipped_files(package)
    for relative in sorted(expected):
        target = package / relative
        if not target.is_file() or target.read_bytes() != (source / relative).read_bytes():
            raise ValueError(f"installed OMP surface is stale or differs from source: {target}")
    if extras := actual - expected:
        raise ValueError(f"unexpected installed OMP shipped surface: {package / sorted(extras)[0]}")
    return len(expected)


def verify_runtime(package: Path) -> None:
    bun = os.environ.get("BUN_BIN", "bun")
    if not shutil.which(bun):
        raise ValueError(f"OMP runtime verifier requires Bun: {bun}")
    with tempfile.TemporaryDirectory(prefix="escapement-omp-verify-") as temporary:
        root = Path(temporary)
        primary, linked = root / "primary", root / "linked"
        subprocess.run(["git", "init", "-q", "-b", "main", str(primary)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-c", "user.name=Escapement deployment probe",
                        "-c", "user.email=deployment@example.invalid", "-c", "commit.gpgsign=false",
                        "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "probe"],
                       cwd=primary, check=True, capture_output=True, text=True)
        subprocess.run(["git", "worktree", "add", "-q", "-b", "probe", str(linked)],
                       cwd=primary, check=True, capture_output=True, text=True)
        (primary / ".beads").mkdir()
        devices = ["xd://github", "xd://report_issue", "xd://mcp__serena_initial_instructions"]
        calls = [{"cwd": str(primary), "path": path} for path in devices]
        calls += [{"cwd": str(primary), "path": str(primary / "ordinary.txt")},
                  {"cwd": str(linked), "path": str(linked / "ordinary.txt")}]
        probe = root / "probe.mjs"
        probe.write_text(PROBE)
        state = root / "state"
        state.mkdir()
        home = root / "home"
        home.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CLAUDE_", "CODEX_", "ESCAPEMENT_", "BEADS_"))}
        env.update(HOME=str(home), HARNESS_ROOT=str(state), CONTINUATION_HARNESS_HOME=str(state),
                   GATE_SIGNAL_FALLBACK_DIR=str(state), ESCAPEMENT_LOCAL_JUDGE_BASE_URL="http://127.0.0.1:9/v1",
                   ESCAPEMENT_LOCAL_JUDGE_TIMEOUT="1", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([bun, str(probe),
                                 (package / "plugins/escapement-pi/extensions/index.ts").as_uri(),
                                 json.dumps(calls)], cwd=root, env=env, capture_output=True,
                                text=True, timeout=60, check=False)
        if result.returncode:
            raise ValueError(f"installed OMP runtime probe failed: {result.stderr.strip()}")
        outcomes = json.loads(result.stdout)
        if len(outcomes) != len(calls):
            raise ValueError("installed OMP runtime returned incomplete outcomes")
        for path, outcome in zip(devices, outcomes[:3]):
            if outcome is not None:
                raise ValueError(f"installed OMP runtime incorrectly blocks {path}: {outcome}")
        denial = outcomes[3]
        if (not isinstance(denial, dict) or denial.get("block") is not True
                or "primary checkout" not in denial.get("reason", "")):
            raise ValueError(f"installed OMP runtime did not deny real primary checkout write: {denial}")
        if outcomes[4] is not None:
            raise ValueError(f"installed OMP runtime incorrectly blocks linked worktree write: {outcomes[4]}")
        print("Runtime verified: " + ", ".join(devices) + " allowed; root write denied; linked write allowed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugins-dir", type=Path,
                        default=Path(os.environ.get("OMP_PLUGIN_DIR", str(Path.home() / ".omp/plugins"))))
    parser.add_argument("--upgrade", action="store_true")
    args = parser.parse_args()
    try:
        plugins = args.plugins_dir.resolve()
        if args.upgrade and not plugins.exists() and not plugins.parent.exists():
            print(f"SKIP: OMP is not installed at {plugins.parent}")
            return 0
        package, manifest, runtime = registration(plugins)
        if args.upgrade:
            other_data = unrelated_plugin_data(plugins, manifest)
            omp = os.environ.get("OMP_BIN", "omp")
            if not shutil.which(omp):
                raise ValueError(f"OMP CLI not found: {omp}")
            # The recorded rolling source remains owned by OMP's package manager.
            result = subprocess.run([omp, "plugin", "upgrade", "escapement"], check=False,
                                    stdin=subprocess.DEVNULL, timeout=300)
            if result.returncode:
                raise ValueError(f"OMP plugin upgrade failed (exit {result.returncode})")
            package, after_manifest, after_runtime = registration(plugins)
            if after_manifest != manifest:
                raise ValueError("OMP plugin upgrade changed registered dependencies or package configuration")
            if settings_without_version(after_runtime) != settings_without_version(runtime):
                raise ValueError("OMP plugin upgrade changed enablement, features or settings")
            if unrelated_plugin_data(plugins, after_manifest) != other_data:
                raise ValueError("OMP plugin upgrade changed unrelated registered plugin files or data")
        count = verify_bytes(args.source.resolve(), package)
        verify_runtime(package)
        print(f"OK: OMP Escapement installed at {package}; {count} shipped files match {args.source.resolve()}.")
        if args.upgrade:
            print("Reload existing OMP sessions to load the refreshed plugin.")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FATAL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
