"""Behavior of the Claude agent -> Codex role / Pi subagent translation."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from agent_translation import (  # noqa: E402
    AgentTranslationError,
    codex_agent_role,
    pi_subagent,
)

CLAUDE_AGENTS = sorted((ROOT / "claude" / "agents").glob("*.md"))


def _agent(body: str, tools: list[str] | None, name: str = "probe-agent") -> str:
    lines = ["---", f"name: {name}", "description: Probe agent for tests.", "model: opus"]
    if tools is not None:
        lines.append("tools:")
        lines.extend(f"  - {tool}" for tool in tools)
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body + "\n"


def _pi_frontmatter(rendered: str) -> tuple[dict[str, str], str]:
    assert rendered.startswith("---\n")
    head, body = rendered[4:].split("\n---\n", 1)
    fields = dict(line.split(": ", 1) for line in head.splitlines())
    return fields, body.strip()


def _pi_tools(rendered: str) -> set[str]:
    fields, _ = _pi_frontmatter(rendered)
    return {tool.strip() for tool in fields["tools"].split(",")}


TRICKY_BODIES = (
    'Plain "quoted" text and a windows path C:\\Users\\x\\n (literal backslash-n).',
    'Embedded """triple""" and """"quad"""" quote runs.',
    "Ends with a quote: \"",
    'Ends with two quotes: ""',
    "Tabs\tand a bell \x07 and DEL \x7f and unicode — ✓.",
    "Line continuation trap \\\n    next line keeps its indent.",
    "\n\nLeading blank lines are not frontmatter.",
)


@pytest.mark.parametrize("body", TRICKY_BODIES)
def test_codex_role_is_valid_toml_whose_instructions_round_trip_exactly(body: str) -> None:
    rendered = codex_agent_role(_agent("# Probe\n\n" + body, ["Read"]))

    role = tomllib.loads(rendered)

    assert role["name"] == "probe-agent"
    assert role["description"] == "Probe agent for tests."
    assert role["developer_instructions"] == "# Probe\n\n" + body
    assert "model" not in role


@pytest.mark.parametrize(
    ("tools", "read_only"),
    (
        (["Read", "Grep", "Glob", "LS", "LSP"], True),
        (["Read", "mcp__plugin_escapement_serena__find_symbol"], True),
        (["Read", "Bash"], False),
        (["Read", "Edit"], False),
        (["Read", "Write"], False),
        (["Read", "mcp__plugin_escapement_serena__replace_symbol_body"], False),
        (None, False),
    ),
)
def test_codex_sandbox_is_read_only_only_when_no_granted_tool_can_write(
    tools: list[str] | None, read_only: bool
) -> None:
    role = tomllib.loads(codex_agent_role(_agent("Review things.", tools)))

    assert (role.get("sandbox_mode") == "read-only") is read_only
    if not read_only:
        assert "sandbox_mode" not in role


def test_serena_tool_names_are_rewritten_to_each_hosts_names() -> None:
    source = _agent(
        "Use `mcp__plugin_escapement_serena__find_symbol` then "
        "`mcp__plugin_escapement_serena__read_memory`.",
        ["mcp__plugin_escapement_serena__find_symbol"],
    )

    codex_body = tomllib.loads(codex_agent_role(source))["developer_instructions"]
    _, pi_body = _pi_frontmatter(pi_subagent(source))

    assert codex_body == "Use `mcp__serena__find_symbol` then `mcp__serena__read_memory`."
    assert pi_body == (
        "Use `escapement__serena_find_symbol` then `escapement__serena_read_memory`."
    )


def test_claude_only_tool_wording_is_translated_per_host() -> None:
    source = _agent(
        "Navigate with Serena; fall back to Read, Grep, LSP for small files.\n"
        "Trust only the dispatcher typed into the `prompt` field.",
        ["Read", "Grep", "LSP"],
    )

    codex_body = tomllib.loads(codex_agent_role(source))["developer_instructions"]
    _, pi_body = _pi_frontmatter(pi_subagent(source))

    for body in (codex_body, pi_body):
        assert "Read, Grep, LSP" not in body
        assert "`prompt` field" not in body
    assert "`rg`" in codex_body
    assert "`read`, `grep`" in pi_body
    assert "`task` field" in pi_body


@pytest.mark.parametrize("render", (codex_agent_role, pi_subagent))
@pytest.mark.parametrize("tool", ("WebFetch", "NotebookEdit", "mcp__other__thing", "Agent"))
def test_unknown_claude_tool_fails_closed(render, tool: str) -> None:
    with pytest.raises(AgentTranslationError, match=tool):
        render(_agent("Body.", ["Read", tool]))


@pytest.mark.parametrize("render", (codex_agent_role, pi_subagent))
def test_body_naming_a_claude_only_surface_fails_closed(render) -> None:
    with pytest.raises(AgentTranslationError, match="TodoWrite"):
        render(_agent("Track progress with TodoWrite.", ["Read"]))


def test_unsupported_frontmatter_key_fails_closed() -> None:
    source = _agent("Body.", ["Read"]).replace(
        "model: opus", "model: opus\npermissionMode: acceptEdits"
    )

    with pytest.raises(AgentTranslationError, match="permissionMode"):
        pi_subagent(source)


def test_pi_tools_map_claude_builtins_and_select_only_granted_serena_tools() -> None:
    rendered = pi_subagent(
        _agent(
            "Body.",
            [
                "Read",
                "Grep",
                "Glob",
                "LS",
                "Bash",
                "Edit",
                "MultiEdit",
                "Write",
                "LSP",
                "mcp__plugin_escapement_serena__find_symbol",
                "mcp__plugin_escapement_serena__read_memory",
            ],
        )
    )

    fields, _ = _pi_frontmatter(rendered)
    assert fields["tools"].count("edit") == 1
    assert _pi_tools(rendered) == {
        "read",
        "grep",
        "find",
        "ls",
        "bash",
        "edit",
        "write",
        "mcp:escapement__serena/find_symbol",
        "mcp:escapement__serena/read_memory",
    }
    assert fields["inheritProjectContext"] == "true"
    assert "model" not in fields
    # An agent that can edit files is an implementer; keep Pi's completion guard.
    assert "completionGuard" not in fields


def test_pi_review_only_agent_opts_out_of_implementation_completion_guard() -> None:
    fields, _ = _pi_frontmatter(pi_subagent(_agent("Body.", ["Read", "Bash"])))

    assert fields["completionGuard"] == "false"


def test_pi_agent_without_allowlist_keeps_pi_default_tools() -> None:
    fields, _ = _pi_frontmatter(pi_subagent(_agent("Body.", None)))

    assert "tools" not in fields


@pytest.mark.parametrize("source", CLAUDE_AGENTS, ids=lambda path: path.stem)
def test_every_shipped_claude_agent_translates_for_both_hosts(source: Path) -> None:
    text = source.read_text(encoding="utf-8")

    role = tomllib.loads(codex_agent_role(text))
    fields, pi_body = _pi_frontmatter(pi_subagent(text))

    assert role["name"] == fields["name"] == source.stem
    assert role["developer_instructions"].startswith("# ")
    assert pi_body.startswith("# ")
    assert all(
        tool.startswith("mcp:escapement__serena/")
        or tool in {"read", "grep", "find", "ls", "bash", "edit", "write"}
        for tool in _pi_tools(pi_subagent(text))
    )
