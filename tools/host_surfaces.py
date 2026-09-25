"""Rules, commands and agents for every host, declared in the manifest.

Each file under ``claude/rules``, ``claude/commands`` and ``claude/agents`` is
authored once and must reach Claude, Codex and Pi -- or carry an explicit
per-host ``unsupported_reason``. The manifest lists every one (``rules``,
``commands``, ``agents``); this module renders each ready host's copy and
rejects an undeclared file or a ready host with nothing rendered.

Where a host needs different wording, a canon file under ``agent-surfaces/``
projects that host's variant (tools/openspec_projection.py); the projected
text wins over the Claude source.

Host delivery:
- rules: plugin ``rules/`` (Claude) or ``claude/rules/`` (Codex, Pi), injected
  at session start by claude/hooks/inject_rules.py from beside the hook.
- commands: Claude plugin ``commands/``; Pi prompt templates; Codex has no
  command surface, so a Codex-ready command names the skill that delivers it
  (``counterpart``).
- agents: Claude plugin ``agents/``; Codex agent-role TOML (installed into
  ~/.codex/agents by scripts/codex-plugin-update.sh); Pi pi-subagents markdown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

try:
    from agent_translation import codex_agent_role, pi_subagent
except ModuleNotFoundError:
    from tools.agent_translation import codex_agent_role, pi_subagent

CLAUDE_PLUGIN = Path("plugins/escapement-claude")
CODEX_PLUGIN = Path("plugins/escapement")
PI_PLUGIN = Path("plugins/escapement-pi")

SOURCE_DIRS = {
    "rules": Path("claude/rules"),
    "commands": Path("claude/commands"),
    "agents": Path("claude/agents"),
}


def _host_paths(kind: str, name: str) -> dict[str, Path | None]:
    """Where each host's copy of a ``kind`` file named ``name`` is rendered."""
    stem = Path(name).stem
    if kind == "rules":
        return {
            "claude": CLAUDE_PLUGIN / "rules" / name,
            "codex": CODEX_PLUGIN / "claude" / "rules" / name,
            "pi": PI_PLUGIN / "claude" / "rules" / name,
        }
    if kind == "commands":
        return {
            "claude": CLAUDE_PLUGIN / "commands" / name,
            "codex": None,  # delivered by the skill named in `counterpart`
            "pi": PI_PLUGIN / "prompts" / name,
        }
    return {
        "claude": CLAUDE_PLUGIN / "agents" / name,
        "codex": CODEX_PLUGIN / "agents" / f"{stem}.toml",
        "pi": PI_PLUGIN / "agents" / name,
    }


def _content(kind: str, host: str, source_text: str, projected: str | None) -> str:
    if kind == "agents":
        if host == "codex":
            return codex_agent_role(source_text)
        if host == "pi":
            return pi_subagent(source_text)
    return projected if projected is not None else source_text


def render_targets(
    root: Path, manifest: dict[str, Any], projected: dict[Path, str]
) -> dict[Path, str]:
    """Every ready host's rendered rule, command and agent file.

    ``projected`` holds canon projections; a projection of the Claude source
    itself (the canon's claude target) is the source text for every host.
    """
    targets: dict[Path, str] = {}
    for kind in SOURCE_DIRS:
        for entry in manifest.get(kind, []):
            source = root / entry["source"]
            source_text = projected.get(source)
            if source_text is None:
                source_text = source.read_text(encoding="utf-8")
            for host, path in _host_paths(kind, source.name).items():
                status = entry.get("hosts", {}).get(host, {}).get("status")
                if path is None or status != "ready":
                    continue
                target = root / path
                targets[target] = _content(kind, host, source_text, projected.get(target))
    return targets


def validate(
    root: Path,
    manifest: dict[str, Any],
    targets: dict[Path, str],
    all_hosts: tuple[str, ...],
    policy: str,
    validate_host_entry: Callable[[str, str, str, dict[str, Any], list[str]], None],
) -> list[str]:
    errors: list[str] = []
    for kind, directory in SOURCE_DIRS.items():
        label = kind[:-1]
        entries = manifest.get(kind, [])
        declared = {entry.get("source") for entry in entries}
        for path in sorted((root / directory).glob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel not in declared:
                errors.append(f"{label} {rel}: not declared in manifest {kind} ({policy})")
        for entry in entries:
            item_id = entry.get("id", "<missing>")
            source = entry.get("source") or ""
            if not (root / source).is_file():
                errors.append(f"{label} {item_id}: source does not exist: {source}")
                continue
            hosts = entry.get("hosts", {})
            for host, path in _host_paths(kind, Path(source).name).items():
                if host not in all_hosts:
                    continue
                if host not in hosts:
                    errors.append(f"{label} {item_id}: missing host {host} ({policy})")
                    continue
                host_entry = hosts[host]
                validate_host_entry(label, item_id, host, host_entry, errors)
                if host_entry.get("status") != "ready":
                    continue
                if path is not None:
                    if root / path not in targets:
                        errors.append(f"{label} {item_id}: host {host} ready but nothing rendered at {path}")
                    continue
                counterpart = host_entry.get("counterpart")
                if not counterpart:
                    errors.append(f"{label} {item_id}: host {host} ready without a counterpart that delivers it")
                elif root / counterpart not in targets and not (root / counterpart).is_file():
                    errors.append(f"{label} {item_id}: host {host} counterpart does not exist: {counterpart}")
    return errors
