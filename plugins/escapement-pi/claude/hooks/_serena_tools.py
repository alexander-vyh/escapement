"""Serena tool names and guidance, independent of which host is running.

Escapement bundles the Serena MCP server on every host, and each host spells
the same tool differently:

  Claude plugin     mcp__plugin_escapement_serena__find_symbol
  Codex             mcp__serena__find_symbol
  Pi (bundled)      escapement__serena_find_symbol

A hand-configured user-level server adds two more (Claude ``mcp__serena__X``,
Pi ``serena_X``). Hooks that care about Serena tools recognize them through
``serena_tool`` so no gate silently goes dead on one host's spelling, and the
model-facing text names tools by their bare name through ``serena_guidance``.
"""

from __future__ import annotations

import re

_SERENA_TOOL = re.compile(
    r"^(?:mcp__(?:plugin_[A-Za-z0-9_-]+_)?serena__|(?:escapement__)?serena_)"
    r"([a-z][a-z0-9_]*)$"
)

# Serena tools that modify source code.
SERENA_EDIT_TOOLS = frozenset({
    "replace_symbol_body",
    "insert_after_symbol",
    "insert_before_symbol",
    "rename_symbol",
    "replace_content",
})


def serena_tool(tool_name: str) -> str | None:
    """The bare Serena tool name for any host's spelling of it, else None."""
    if not isinstance(tool_name, str):
        return None
    match = _SERENA_TOOL.match(tool_name)
    return match.group(1) if match else None


def is_serena_edit(tool_name: str) -> bool:
    """True when ``tool_name`` is a Serena tool that edits source code."""
    return serena_tool(tool_name) in SERENA_EDIT_TOOLS


def serena_guidance(relative_path: str = "<file>") -> str:
    """How to reach for Serena instead of reading whole source files.

    One text for every host: tools are named bare, and the host prefixes are
    listed once so the model can find them in its own tool list.
    """
    return (
        "Use Serena's symbol tools for source code instead of reading whole files:\n"
        f'  get_symbols_overview(relative_path="{relative_path}") — structure of a file\n'
        f'  find_symbol(name_path="<Symbol>", relative_path="{relative_path}", '
        "include_body=true) — one class/function body\n"
        f'  find_referencing_symbols(name_path="<Symbol>", relative_path="{relative_path}")'
        " — callers and usages\n"
        '  search_for_pattern(substring_pattern="...") — regex search across the project\n'
        "Edit code with replace_symbol_body, insert_after_symbol / "
        "insert_before_symbol, and rename_symbol.\n"
        "Your tool list shows them under a serena prefix: "
        "mcp__plugin_escapement_serena__<tool> (Claude Code), "
        "mcp__serena__<tool> (Codex), escapement__serena_<tool> (Pi)."
    )
