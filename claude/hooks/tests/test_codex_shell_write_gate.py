"""Codex oracle for shell_write_gate: a Bash write reaches the model's context.

Runs the PostToolUse command the generated Codex plugin registers for Bash, on
the captured Codex 0.156.1 Bash payload (see _codex_host), after a real shell
write in a scratch repo. Captured: PostToolUse `additionalContext` reaches the
model verbatim, so that is where the report must be. The docs write is the
silent control, so a hook that reports every dirty file fails.

The PreToolUse half runs first, through the Bash dispatcher Codex registers:
it is the snapshot that tells this session's write apart from dirt already in
a shared checkout, so without it the first write would pass as baseline.
"""

from __future__ import annotations

import subprocess
import uuid

from _codex_host import context, is_allowed, isolated_env, payload, run

POST = "PostToolUse"
PRE = "PreToolUse"


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


def _shell(repo, env, command: str, session: str | None = None) -> dict | None:
    """Codex's PreToolUse hooks, the shell command, then its PostToolUse hook."""
    session = session or f"codex-{uuid.uuid4()}"
    before = payload("pre_tool_use_bash_with_workdir", cwd=str(repo),
                     tool_input={"command": command}, session_id=session)
    assert is_allowed(run(PRE, "shell_write_gate.py", before, env))
    subprocess.run(["bash", "-c", command], cwd=repo, check=True)
    after = payload("post_tool_use_bash_with_workdir", cwd=str(repo),
                    tool_input={"command": command}, session_id=session)
    return run(POST, "shell_write_gate.py", after, env)


def test_codex_shell_write_without_tests_reaches_the_model(tmp_path):
    repo = _repo(tmp_path)
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")  # another session's dirt
    output = _shell(repo, isolated_env(tmp_path),
                    "python3 -c \"open('src/app.py','w').write('VALUE = 2\\n')\"")
    text = context(output, POST)
    assert "TDD" in text and "src/app.py" in text
    assert "legacy.py" not in text, "dirt this session did not write is not its debt"
    assert "test-oracle-brief.md" in text
    assert "once per file per session" in text, "the report must name its escape"


def test_codex_shell_docs_write_is_silent(tmp_path):
    repo = _repo(tmp_path)
    assert _shell(repo, isolated_env(tmp_path), "echo more >> docs/README.md") is None


def test_codex_cd_into_another_repo_is_read_in_both_halves(tmp_path):
    """The PreToolUse dispatcher follows a leading `cd`; the PostToolUse half must
    read the same repository, or it compares the session's repo with the other
    one's snapshot: it blames dirt there and misses the write here."""
    home, other = _repo(tmp_path / "home"), _repo(tmp_path / "other")
    env, session = isolated_env(tmp_path), f"codex-{uuid.uuid4()}"
    assert _shell(home, env, "ls", session) is None
    (home / "src" / "theirs.py").write_text("THEIRS = 1\n")  # another session, in home
    output = _shell(home, env, f"cd {other} && echo 'VALUE = 3' > src/app.py", session)
    text = context(output, POST)
    assert "src/app.py" in text
    assert "theirs.py" not in text, "dirt in the session's repo is not this call's write"
