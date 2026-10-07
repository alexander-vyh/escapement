"""Codex oracle for shell_write_gate: a Bash write reaches the model's context.

Runs the PostToolUse command the generated Codex plugin registers for Bash, on
the captured Codex 0.156.1 Bash payload (see _codex_host), after a real shell
write in a scratch repo. Captured: PostToolUse `additionalContext` reaches the
model verbatim, so that is where the report must be. The docs write is the
silent control, so a hook that reports every dirty file fails.
"""

from __future__ import annotations

import subprocess
import uuid

from _codex_host import context, isolated_env, payload, run

POST = "PostToolUse"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (repo / "src" / "app.py").write_text("VALUE = 1\n")
    (repo / "docs" / "README.md").write_text("demo\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
                   cwd=repo, check=True)
    return repo


def _after_shell(repo, command: str) -> dict:
    subprocess.run(["bash", "-c", command], cwd=repo, check=True)
    return payload("post_tool_use_bash_with_workdir", cwd=str(repo),
                   tool_input={"command": command}, session_id=f"codex-{uuid.uuid4()}")


def test_codex_shell_write_without_tests_reaches_the_model(tmp_path):
    repo = _repo(tmp_path)
    data = _after_shell(repo, "python3 -c \"open('src/app.py','w').write('VALUE = 2\\n')\"")
    text = context(run(POST, "shell_write_gate.py", data, isolated_env(tmp_path)), POST)
    assert "TDD" in text and "src/app.py" in text
    assert "test-oracle-brief.md" in text
    assert "once per file per session" in text, "the report must name its escape"


def test_codex_shell_docs_write_is_silent(tmp_path):
    repo = _repo(tmp_path)
    data = _after_shell(repo, "echo more >> docs/README.md")
    assert run(POST, "shell_write_gate.py", data, isolated_env(tmp_path)) is None
