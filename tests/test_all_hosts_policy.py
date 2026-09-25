"""Every Escapement surface ships to Claude, Codex and Pi unless a host is
explicitly excluded with a reason -- and Serena is one of those surfaces.

The MCP test reads each host package the way that host's loader does:
Claude auto-discovers `.mcp.json` at the plugin root, Codex follows
`.codex-plugin/plugin.json#mcpServers`, and pi-mcp-adapter follows
`package.json#pi.mcp`. A server declared anywhere else is one the host never
starts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "render_agent_surfaces.py"


def _serena_launch_per_host() -> dict[str, dict]:
    claude = ROOT / "plugins" / "escapement-claude" / ".mcp.json"
    codex_root = ROOT / "plugins" / "escapement"
    codex_plugin = json.loads((codex_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    codex = codex_root / codex_plugin["mcpServers"]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pi = ROOT / package["pi"]["mcp"]
    return {
        host: json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["serena"]
        for host, path in (("claude", claude), ("codex", codex), ("pi", pi))
    }


def test_serena_mcp_server_is_declared_for_every_host():
    launches = _serena_launch_per_host()

    pins = set()
    for host, launch in launches.items():
        args = launch["args"]
        assert launch["command"] == "uvx", host
        pin = args[args.index("--from") + 1]
        assert re.fullmatch(r"serena-agent==\d+\.\d+\.\d+", pin), f"{host}: unpinned Serena {pin}"
        pins.add(pin)
        assert "start-mcp-server" in args, host
        # Without this the server starts projectless and every symbol call
        # fails until the agent activates a project by hand.
        assert "--project-from-cwd" in args, host
    assert len(pins) == 1, f"hosts launch different Serena versions: {pins}"

    # Serena's per-host context hides the tools that duplicate that host's own
    # read/shell/edit tools; the wrong one leaves duplicates or hides tools.
    contexts = {host: launch["args"][launch["args"].index("--context") + 1] for host, launch in launches.items()}
    assert contexts == {"claude": "claude-code", "codex": "codex", "pi": "ide"}


def test_surfaces_missing_a_host_fail_the_render(tmp_path):
    temp_root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        temp_root,
        ignore=shutil.ignore_patterns(".git", ".worktrees", ".agent-surface-stage-*", "__pycache__", ".pytest_cache"),
    )
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hooks = {hook["id"]: hook for hook in manifest["hooks"]}
    # A hook Pi cannot derive from Codex, with its explicit exclusion removed.
    del hooks["review_nudge"]["hosts"]["pi"]
    # A Pi event the extension never translates.
    hooks["session_status"]["hosts"]["pi"] = {
        "status": "ready",
        "events": [{"event": "Stop", "matcher": "", "command": "python3 -B x.py", "timeout_seconds": 5}],
        "fixtures": ["tests/test_all_hosts_policy.py"],
    }
    del manifest["skills"][0]["hosts"]["pi"]
    del manifest["mcp_servers"][0]["hosts"]["codex"]
    # A rule file nobody declared, a rule and an agent missing a host, and a
    # command claimed ready on Codex with nothing that delivers it.
    (temp_root / "claude" / "rules" / "undeclared-rule.md").write_text("# Undeclared\n", encoding="utf-8")
    rules = {rule["id"]: rule for rule in manifest["rules"]}
    del rules["never-suppress"]["hosts"]["codex"]
    del manifest["agents"][0]["hosts"]["pi"]
    commands = {command["id"]: command for command in manifest["commands"]}
    del commands["brainstorm"]["hosts"]["codex"]["counterpart"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RENDERER), "--check"], cwd=temp_root, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "hook review_nudge: missing host pi" in result.stderr
    assert "hook session_status: Pi event 'Stop' is not translated" in result.stderr
    assert f"skill {manifest['skills'][0]['id']}: missing host pi" in result.stderr
    assert "mcp server serena: missing host codex" in result.stderr
    assert "rule claude/rules/undeclared-rule.md: not declared in manifest rules" in result.stderr
    assert "rule never-suppress: missing host codex" in result.stderr
    assert f"agent {manifest['agents'][0]['id']}: missing host pi" in result.stderr
    assert "command brainstorm: host codex ready without a counterpart" in result.stderr
    # Positive control: a gate Pi derives from its Codex Bash entry needs no
    # explicit block and is not reported.
    assert "test_oracle_brief_gate" not in result.stderr
