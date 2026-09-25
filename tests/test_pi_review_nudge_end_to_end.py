"""Drive the rendered Pi extension with a submitted prompt and see
review_nudge act on Pi: a review request gets the nudge in that turn's system
prompt, naming the /review prompt and the reviewer agents the Pi package
ships; any other prompt hears nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

NUDGE = "Review request detected"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _system_prompt(plugin: Path, tmp_path: Path, text: str) -> str:
    repo = git_repo(tmp_path / "project", {"README.md": "demo\n"})
    (outcome,) = run(plugin, [Session(repo).prompt(text)], pi_env(tmp_path))
    return outcome["result"]["systemPrompt"]


def test_pi_review_prompt_gets_review_nudge(plugin, tmp_path):
    prompt = _system_prompt(plugin, tmp_path, "Please review this pull request before I merge it")

    assert prompt.startswith("BASE PROMPT")
    assert NUDGE in prompt
    assert "/review" in prompt and (plugin / "prompts" / "review.md").is_file()
    for agent in ("adversarial-reviewer", "test-quality-reviewer"):
        assert agent in prompt and (plugin / "agents" / f"{agent}.md").is_file(), agent


def test_pi_non_review_prompt_is_silent(plugin, tmp_path):
    """Negative control: a fix request is not a review request."""
    prompt = _system_prompt(plugin, tmp_path, "Fix the typo in the README heading")

    assert NUDGE not in prompt
