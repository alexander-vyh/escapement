"""Drive the rendered Pi extension with a submitted prompt and see
discovery-nudge act on Pi: a feature prompt in a project with no recent design
gets the nudge in that turn's system prompt, pointing at the /discovery prompt
the Pi package ships; a project with a fresh design doc hears nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

NUDGE = "No design doc from the last 30 days"
FEATURE = "Implement a new feature that exports reports as CSV"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _system_prompt(plugin: Path, tmp_path: Path, files: dict[str, str]) -> str:
    repo = git_repo(tmp_path / "project", {"README.md": "demo\n", **files})
    (outcome,) = run(plugin, [Session(repo).prompt(FEATURE)], pi_env(tmp_path))
    return outcome["result"]["systemPrompt"]


def test_pi_feature_prompt_without_design_gets_discovery_nudge(plugin, tmp_path):
    prompt = _system_prompt(plugin, tmp_path, {})

    assert prompt.startswith("BASE PROMPT")
    assert NUDGE in prompt
    assert "/discovery" in prompt
    assert (plugin / "prompts" / "discovery.md").is_file(), "the nudge names a Pi prompt that must ship"


def test_pi_feature_prompt_with_recent_design_is_silent(plugin, tmp_path):
    """Negative control: the design exists, so there is nothing to nudge toward."""
    prompt = _system_prompt(plugin, tmp_path, {"docs/plans/2026-09-24-csv-export.md": "# CSV export\n"})

    assert NUDGE not in prompt
