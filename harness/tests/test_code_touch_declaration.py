"""A session that changed code must have declared an outcome (escapement-pip5).

Business outcome
----------------
"A goal must exist, and code is checked against the desired outcome." The
requirement is DERIVED from what the session actually did, never declared by the
agent — `would_block_stop.py:112` states that law for this file: "A DERIVED
signal (gate-design Rule 3 / derive-not-assert) — never agent-asserted." An
agent-chosen `kind` would be an assertion, and an advisory panel showed the
previous self-declared exemption decayed from 20.5% verified stops (May) to 0%
(Aug/Sep) once introduced.

So: touched code + no contract -> block. Touched nothing -> stop freely. There is
no menu to game and no front door to make cheaper, because conversations are
never gated.

Independent source of truth
---------------------------
The session's own transcript — the file the Stop hook already reads. Detection is
a pure function over it, so it is session-local by construction and immune to the
shared-checkout problem where a peer's in-flight edits would otherwise implicate
this session.

Invalid solution classes rejected here
--------------------------------------
- **Instrumenting only Write/Edit.** The host's auto mode instructs agents to
  "make file changes with sed, heredocs, or short scripts, rather than using the
  dedicated Read, Edit, or Write tools." A detector blind to Bash-mediated writes
  would be blind precisely in unattended sessions. `test_bash_*` cover this.
- **Counting any file write.** Scratchpad, /tmp, and gitignored paths ship
  nothing, so there is no outcome to check them against. Demanding an oracle for
  a temp script is the compliance theatre `delicate-art-of-bureaucracy.md`
  forbids, and would train agents to declare a fake contract to clear a gate
  tripped by a scratch file.
- **Blocking on contract PRESENCE.** A session that touched nothing must still
  stop with no contract at all.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import code_touch  # noqa: E402
from would_block_stop import would_block_stop  # noqa: E402


def _git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "build").mkdir()
    return repo


def _transcript(tmp_path: pathlib.Path, tool_calls: list[dict]) -> str:
    """A Claude Code transcript containing the given assistant tool_use blocks."""
    path = tmp_path / "transcript.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": "do the thing"}}]
    for call in tool_calls:
        rows.append(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": call["name"], "input": call["input"]}
                    ],
                },
            }
        )
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------
# Detection: what counts as touching code
# --------------------------------------------------------------------------


def test_write_tool_on_a_repo_file_counts(tmp_path):
    repo = _git_repo(tmp_path)
    t = _transcript(
        tmp_path, [{"name": "Write", "input": {"file_path": str(repo / "src" / "app.py")}}]
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is True


def test_edit_tool_on_a_repo_file_counts(tmp_path):
    repo = _git_repo(tmp_path)
    t = _transcript(
        tmp_path, [{"name": "Edit", "input": {"file_path": str(repo / "src" / "app.py")}}]
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is True


@pytest.mark.parametrize(
    "command",
    [
        "sed -i '' 's/x/y/' {f}",
        "cat > {f} <<'EOF'\nx = 2\nEOF",
        "echo 'x = 2' > {f}",
        "echo 'more' >> {f}",
        "tee {f} < /dev/null",
        "python3 - <<'PY' > {f}\nprint(1)\nPY",
    ],
)
def test_bash_mediated_writes_count(tmp_path, command):
    """THE BYPASS THAT MATTERS.

    Host auto mode tells agents to prefer sed/heredocs over Write/Edit. A detector
    that only sees edit tools reports clean while the session rewrites the repo.
    """
    repo = _git_repo(tmp_path)
    target = repo / "src" / "app.py"
    t = _transcript(
        tmp_path, [{"name": "Bash", "input": {"command": command.format(f=target)}}]
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is True, (
        f"Bash-mediated write not detected: {command!r}"
    )


def test_bash_read_only_commands_do_not_count(tmp_path):
    """CONTROL: reading, searching and testing are not code changes."""
    repo = _git_repo(tmp_path)
    t = _transcript(
        tmp_path,
        [
            {"name": "Bash", "input": {"command": f"cat {repo / 'src' / 'app.py'}"}},
            {"name": "Bash", "input": {"command": "grep -rn foo ."}},
            {"name": "Bash", "input": {"command": "python3 -m pytest -q"}},
            {"name": "Bash", "input": {"command": "git status --porcelain"}},
        ],
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is False


@pytest.mark.parametrize(
    "command",
    [
        # The reported case: a Python comparison read as a shell redirect.
        "python3 - <<'EOF'\nif len(v) > 2000:\n    print(1)\nEOF",
        # `>=` is the same shape.
        "python3 - <<'EOF'\nif count >= 5:\n    print(1)\nEOF",
        # Unquoted delimiter, and a tab-stripping heredoc.
        "python3 - <<EOF\nrows = [r for r in rs if r > limit]\nEOF",
        "python3 - <<-EOF\n\tif a > b:\n\t\tpass\nEOF",
        # Other interpreters agents pipe through heredocs.
        "jq -r <<'EOF'\nmap(select(.n > threshold))\nEOF",
        "awk -f - data.txt <<'EOF'\n$1 > cutoff { print }\nEOF",
    ],
)
def test_heredoc_body_text_is_not_a_shell_redirect(tmp_path, command):
    """THE FALSE POSITIVE THAT TRAINS FAKE CONTRACTS.

    Auto mode tells agents to extract data with heredoc'd Python/jq/awk, so
    comparison operators inside heredoc bodies are routine. Scanning that body as
    if it were shell reads `len(v) > 2000:` as a redirect to a file named
    `2000:`, and a read-only session gets told it changed code.

    That is the exact harm `bash_write_targets` is written to avoid: the module
    docstring refuses to count scratch writes because demanding an oracle for one
    "would just train agents to declare a fake contract to clear a gate". A
    phantom target does the same thing, with no file anywhere on disk.
    """
    repo = _git_repo(tmp_path)
    t = _transcript(tmp_path, [{"name": "Bash", "input": {"command": command}}])
    assert code_touch.touched_code(t, cwd=str(repo)) is False, (
        f"heredoc body text misread as a write: {command!r}"
    )


def test_redirect_on_the_heredoc_opening_line_still_counts(tmp_path):
    """RECALL GUARD: the body is inert, the opening line is not.

    A heredoc only writes a file via a redirect on its opening line, which sits
    outside the body. Stripping bodies must not blind the detector to that.
    """
    repo = _git_repo(tmp_path)
    target = repo / "src" / "app.py"
    t = _transcript(
        tmp_path,
        [{"name": "Bash", "input": {"command": f"cat > {target} <<'EOF'\nx = 2\nEOF"}}],
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is True


def test_shell_interpreted_heredoc_body_still_counts(tmp_path):
    """RECALL GUARD: a body fed to a shell IS shell, so it must still be scanned."""
    repo = _git_repo(tmp_path)
    target = repo / "src" / "app.py"
    t = _transcript(
        tmp_path,
        [{"name": "Bash", "input": {"command": f"bash <<'EOF'\necho hi > {target}\nEOF"}}],
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is True


def test_scratchpad_writes_do_not_count(tmp_path):
    """CONTROL: a scratch analysis script ships nothing, so there is no outcome."""
    repo = _git_repo(tmp_path)
    scratch = tmp_path / "scratchpad" / "probe.py"
    scratch.parent.mkdir()
    t = _transcript(tmp_path, [{"name": "Write", "input": {"file_path": str(scratch)}}])
    assert code_touch.touched_code(t, cwd=str(repo)) is False


def test_tmp_writes_do_not_count(tmp_path):
    """CONTROL: /tmp is outside any git tree."""
    repo = _git_repo(tmp_path)
    t = _transcript(
        tmp_path, [{"name": "Bash", "input": {"command": "echo hi > /tmp/probe.txt"}}]
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is False


def test_gitignored_paths_do_not_count(tmp_path):
    """CONTROL: build artifacts and logs are not shipped source."""
    repo = _git_repo(tmp_path)
    t = _transcript(
        tmp_path,
        [
            {"name": "Write", "input": {"file_path": str(repo / "build" / "out.js")}},
            {"name": "Write", "input": {"file_path": str(repo / "run.log")}},
        ],
    )
    assert code_touch.touched_code(t, cwd=str(repo)) is False


def test_a_read_only_session_touches_nothing(tmp_path):
    repo = _git_repo(tmp_path)
    t = _transcript(tmp_path, [{"name": "Read", "input": {"file_path": str(repo / "src" / "app.py")}}])
    assert code_touch.touched_code(t, cwd=str(repo)) is False


def test_missing_transcript_is_not_a_code_touch(tmp_path):
    """Fail OPEN on missing evidence: absence of a transcript must not manufacture
    a block. The gate may only block on positive proof that code changed."""
    repo = _git_repo(tmp_path)
    assert code_touch.touched_code("", cwd=str(repo)) is False
    assert code_touch.touched_code(str(tmp_path / "nope.jsonl"), cwd=str(repo)) is False


# --------------------------------------------------------------------------
# The decision: the requirement is derived, never declared
# --------------------------------------------------------------------------


def test_touched_code_without_a_contract_blocks():
    """THE FEATURE. No contract + changed code -> the session may not stop."""
    decision, reason = would_block_stop(
        {"contract": None, "scheduled": None, "recent_user_message": None,
         "touched_code": True}
    )
    assert (decision, reason) == ("block", "no_declaration")


def test_touched_nothing_without_a_contract_still_stops():
    """CONTROL: the conversational population labels 5,528 correct vs 4 wrong.
    It must pay no tax at all."""
    decision, reason = would_block_stop(
        {"contract": None, "scheduled": None, "recent_user_message": None,
         "touched_code": False}
    )
    assert (decision, reason) == ("allow", "conversational")


def test_user_release_still_wins_over_a_code_touch():
    """CONTROL: the human can always end the turn. A derived requirement must not
    outrank an explicit release — that would be a gate with no escape."""
    decision, reason = would_block_stop(
        {"contract": None, "scheduled": None, "recent_user_message": "stop",
         "touched_code": True}
    )
    assert decision == "allow"


def test_wakeup_still_wins_over_a_code_touch():
    """CONTROL: a registered resumption is the sanctioned pause."""
    import datetime as dt

    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    decision, reason = would_block_stop(
        {"contract": None, "scheduled": [{"wake_at": future}],
         "recent_user_message": None, "touched_code": True}
    )
    assert decision == "allow"
