import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
HOOK_PATH = TEST_DIR / "test_oracle_brief_gate.py"
if not HOOK_PATH.exists():
    HOOK_PATH = TEST_DIR.parent / "test_oracle_brief_gate.py"
spec = importlib.util.spec_from_file_location("test_oracle_brief_gate", HOOK_PATH)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gate)
sys.modules["test_oracle_brief_gate"] = gate


def valid_brief() -> str:
    return "\n".join(f"## {section}\nTBD\n" for section in gate.REQUIRED_SECTIONS)


def run_hook(payload: dict) -> tuple[int, dict | None]:
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("sys.stdout", stdout):
            code = gate.main()
    output = stdout.getvalue().strip()
    # json.loads raises on a second concatenated document, so a clean parse is
    # part of the EXACTLY-ONCE guarantee (no stacked block signals).
    return code, json.loads(output) if output else None


def assert_denied(code: int, output: dict | None) -> None:
    """Assert the hard block was honored EXACTLY ONCE via the canonical
    mechanism: a single permissionDecision="deny" JSON document on stdout AND
    exit code 0 (NOT exit 2). A deny JSON *plus* exit 2 is a contradictory
    double-block; asserting exit 0 rejects that shape.
    """
    assert code == 0, (
        "deny is carried by the stdout JSON decision, not exit 2 — "
        "permissionDecision=deny plus exit 2 is a contradictory double-block"
    )
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def write_valid_brief(repo: Path) -> None:
    brief = repo / gate.BRIEF_RELATIVE_PATH
    brief.parent.mkdir(parents=True)
    brief.write_text(valid_brief(), encoding="utf-8")


def init_repo(tmp_path: Path) -> Path:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_required_section_detection_accepts_markdown_headings(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text(valid_brief(), encoding="utf-8")

    assert gate.missing_brief_sections(path) == []


def test_required_section_detection_reports_missing_heading(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("## Business invariant\n", encoding="utf-8")

    missing = gate.missing_brief_sections(path)

    assert "Independent source of truth" in missing


def test_claude_edit_blocks_relevant_file_without_brief(tmp_path):
    repo = init_repo(tmp_path)
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('x')\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    assert "test-oracle-brief.md" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_claude_edit_allows_relevant_file_with_valid_brief(tmp_path):
    repo = init_repo(tmp_path)
    write_valid_brief(repo)
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('x')\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None


def test_claude_edit_allows_docs_without_brief(tmp_path):
    repo = init_repo(tmp_path)
    target = repo / "docs" / "plan.md"
    target.parent.mkdir()
    target.write_text("# Plan\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None


def test_codex_commit_blocks_changed_code_without_brief(tmp_path):
    repo = init_repo(tmp_path)
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('x')\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    assert "src/app.py" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_commit_allows_changed_code_with_valid_brief(tmp_path):
    repo = init_repo(tmp_path)
    write_valid_brief(repo)
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('x')\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None


def test_codex_non_finishing_bash_allows_without_brief(tmp_path):
    repo = init_repo(tmp_path)
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('x')\n", encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "pytest"},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None
