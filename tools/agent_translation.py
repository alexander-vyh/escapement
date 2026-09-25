"""Translate Escapement's Claude subagent files for Codex and Pi.

The source of truth is ``claude/agents/<name>.md``: limited-YAML frontmatter
(``name``, ``description``, ``model``, ``tools``, optional ``color``) followed
by the system prompt body.  Two projections are produced:

* ``codex_agent_role`` -> a Codex agent role TOML (``~/.codex/agents/<name>.toml``)
  with ``name``, ``description``, ``developer_instructions`` and, when the
  Claude tool allowlist grants nothing that can write, ``sandbox_mode =
  "read-only"``.  Codex roles cannot restrict individual tools, so the sandbox
  is the only least-privilege lever; ``model`` is omitted so the role inherits.
* ``pi_subagent`` -> a pi-subagents agent markdown file whose strict ``tools``
  allowlist mirrors the Claude one (Serena tools become per-tool direct MCP
  selections on the bundled ``escapement__serena`` server).

Both fail closed: an unrecognized Claude tool or frontmatter key raises
``AgentTranslationError`` instead of being dropped, and a translated body that
still names a Claude-only surface raises as well.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass


class AgentTranslationError(ValueError):
    """A Claude agent cannot be faithfully translated for the target host."""


CLAUDE_SERENA_PREFIX = "mcp__plugin_escapement_serena__"
CODEX_SERENA_PREFIX = "mcp__serena__"
# pi-mcp-adapter namespaces package servers as <package>__<server>; direct tools
# are exposed as <server>_<tool>.
PI_SERENA_SERVER = "escapement__serena"
PI_SERENA_PREFIX = f"{PI_SERENA_SERVER}_"

# Serena tools that only observe the project.  Any other Serena tool may write.
SERENA_READ_ONLY = frozenset(
    {
        "check_onboarding_performed",
        "find_file",
        "find_referencing_symbols",
        "find_symbol",
        "get_symbols_overview",
        "list_dir",
        "list_memories",
        "read_file",
        "read_memory",
        "search_for_pattern",
    }
)

# Claude builtin tool -> Pi builtin tool (None: no Pi equivalent; dropped with
# the reason recorded here).  Tools absent from this table are unknown and
# raise.
CLAUDE_TO_PI_TOOL: dict[str, str | None] = {
    "Read": "read",
    "Grep": "grep",
    "Glob": "find",
    "LS": "ls",
    "Bash": "bash",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Write": "write",
    # Pi ships no LSP tool; Serena's symbol tools cover code navigation.
    "LSP": None,
}
CLAUDE_WRITE_CAPABLE = frozenset({"Bash", "Edit", "MultiEdit", "Write"})

# Claude-only wording in agent bodies -> host wording.  Every entry is a
# reference to a Claude tool or Agent-tool parameter that does not exist on
# the other hosts.
BODY_REWRITES: dict[str, dict[str, str]] = {
    "fall back to Read, Grep, LSP for": {
        "codex": "fall back to shell reads and `rg` for",
        "pi": "fall back to `read`, `grep` for",
    },
    "the dispatcher typed into the `prompt` field": {
        "codex": "the dispatcher typed into the spawn message",
        "pi": "the dispatcher typed into the `task` field",
    },
}

# Tokens that must never survive into a non-Claude agent body.
NON_CLAUDE_FORBIDDEN = (
    CLAUDE_SERENA_PREFIX,
    "~/.claude",
    "CLAUDE_CODE_SESSION_ID",
    "ScheduleWakeup",
    "TeamCreate",
    "SendMessage",
    "TodoWrite",
    "AskUserQuestion",
    "Task tool",
    "subagent_type",
)

_ALLOWED_KEYS = frozenset({"name", "description", "model", "tools", "color"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class ClaudeAgent:
    name: str
    description: str
    tools: tuple[str, ...] | None
    body: str


def parse_claude_agent(source_text: str) -> ClaudeAgent:
    """Parse a ``claude/agents/<name>.md`` file."""
    text = source_text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise AgentTranslationError("agent file must start with '---' frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise AgentTranslationError("agent frontmatter is not closed by '---'")
    fields: dict[str, str | list[str]] = {}
    current_list: list[str] | None = None
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        item = re.match(r"^\s+-\s+(.+?)\s*$", line)
        if item:
            if current_list is None:
                raise AgentTranslationError(f"list item outside a list: {line!r}")
            current_list.append(item.group(1))
            continue
        pair = re.match(r"^([A-Za-z][\w-]*):\s*(.*?)\s*$", line)
        if not pair:
            raise AgentTranslationError(f"unsupported frontmatter line: {line!r}")
        key, value = pair.groups()
        if key not in _ALLOWED_KEYS:
            raise AgentTranslationError(f"unsupported agent frontmatter key: {key}")
        if key in fields:
            raise AgentTranslationError(f"duplicate agent frontmatter key: {key}")
        if value:
            fields[key] = value
            current_list = None
        else:
            current_list = []
            fields[key] = current_list

    name = fields.get("name")
    description = fields.get("description")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise AgentTranslationError(f"agent name must be a lowercase slug, got {name!r}")
    if not isinstance(description, str) or not description:
        raise AgentTranslationError(f"agent {name} has no description")
    raw_tools = fields.get("tools")
    if raw_tools is None:
        tools = None
    elif isinstance(raw_tools, list):
        tools = tuple(raw_tools)
    else:
        tools = tuple(part.strip() for part in raw_tools.split(",") if part.strip())
    for tool in tools or ():
        _classify(tool)
    body = text[end + len("\n---\n"):].strip("\n")
    if not body.strip():
        raise AgentTranslationError(f"agent {name} has an empty body")
    return ClaudeAgent(name=name, description=description, tools=tools, body=body)


def _classify(tool: str) -> tuple[str, bool]:
    """Return (kind, may_write) for a Claude tool name; raise when unknown."""
    if tool.startswith(CLAUDE_SERENA_PREFIX):
        serena_tool = tool[len(CLAUDE_SERENA_PREFIX):]
        if not re.fullmatch(r"[a-z_]+", serena_tool):
            raise AgentTranslationError(f"malformed Serena tool name: {tool}")
        return "serena", serena_tool not in SERENA_READ_ONLY
    if tool in CLAUDE_TO_PI_TOOL:
        return "builtin", tool in CLAUDE_WRITE_CAPABLE
    raise AgentTranslationError(f"no Codex/Pi translation for Claude tool: {tool}")


def _translate_body(body: str, host: str) -> str:
    for claude_text, variants in BODY_REWRITES.items():
        body = body.replace(claude_text, variants[host])
    replacement = CODEX_SERENA_PREFIX if host == "codex" else PI_SERENA_PREFIX
    body = body.replace(CLAUDE_SERENA_PREFIX, replacement)
    leaked = [token for token in NON_CLAUDE_FORBIDDEN if token in body]
    if leaked:
        raise AgentTranslationError(
            f"{host} agent body still names Claude-only surfaces: {', '.join(leaked)}"
        )
    return body


def _toml_basic(value: str) -> str:
    out = []
    for char in value:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _toml_multiline(value: str) -> str:
    out = []
    for char in value:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char in "\n\t":
            out.append(char)
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(char)
    escaped = "".join(out)
    # A run of three quotes would close the string; a trailing quote would merge
    # with the closing delimiter.  Escape every quote in such runs.
    escaped = re.sub(
        r'"{3,}|"+\Z', lambda match: '\\"' * len(match.group(0)), escaped
    )
    # The newline right after the opening delimiter is trimmed by TOML.
    return '"""\n' + escaped + '"""'


def codex_agent_role(source_text: str) -> str:
    """Render a Claude agent as a Codex agent role TOML document."""
    agent = parse_claude_agent(source_text)
    # No allowlist means every Claude tool, which includes writers.
    may_write = agent.tools is None or any(_classify(tool)[1] for tool in agent.tools)
    lines = [
        f"name = {_toml_basic(agent.name)}",
        f"description = {_toml_basic(agent.description)}",
    ]
    if not may_write:
        lines.append('sandbox_mode = "read-only"')
    lines.append(
        f"developer_instructions = {_toml_multiline(_translate_body(agent.body, 'codex'))}"
    )
    return "\n".join(lines) + "\n"


def _pi_tools(tools: tuple[str, ...]) -> list[str]:
    builtins: list[str] = []
    serena: list[str] = []
    for tool in tools:
        kind, _ = _classify(tool)
        if kind == "serena":
            selector = f"mcp:{PI_SERENA_SERVER}/{tool[len(CLAUDE_SERENA_PREFIX):]}"
            if selector not in serena:
                serena.append(selector)
            continue
        mapped = CLAUDE_TO_PI_TOOL[tool]
        if mapped is not None and mapped not in builtins:
            builtins.append(mapped)
    return builtins + serena


def pi_subagent(source_text: str) -> str:
    """Render a Claude agent as a pi-subagents agent markdown file."""
    agent = parse_claude_agent(source_text)
    if "\n" in agent.description or agent.description[:1] in {'"', "'", "|", ">"}:
        raise AgentTranslationError(
            f"agent {agent.name} description cannot be a plain pi-subagents scalar"
        )
    lines = ["---", f"name: {agent.name}", f"description: {agent.description}"]
    if agent.tools is not None:
        tools = _pi_tools(agent.tools)
        if not tools:
            raise AgentTranslationError(
                f"agent {agent.name} has no Pi-available tools after translation"
            )
        lines.append(f"tools: {', '.join(tools)}")
    # Claude subagents see the project's CLAUDE.md; keep that parity on Pi.
    lines.append("inheritProjectContext: true")
    if agent.tools is not None and not any(
        tool in {"Edit", "MultiEdit", "Write"} for tool in agent.tools
    ):
        # Review-only agents: bash/MCP make pi-subagents treat them as
        # mutation-capable, so opt out of the implementation completion guard.
        lines.append("completionGuard: false")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + _translate_body(agent.body, "pi") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", choices=("codex", "pi"))
    parser.add_argument("source", help="claude/agents/<name>.md")
    args = parser.parse_args(argv)
    with open(args.source, encoding="utf-8") as stream:
        source = stream.read()
    render = codex_agent_role if args.host == "codex" else pi_subagent
    try:
        sys.stdout.write(render(source))
    except AgentTranslationError as error:
        print(f"agent_translation: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
