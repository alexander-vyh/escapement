import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
HOOK_PATH = TEST_DIR / "oracle_downgrade_warning_gate.py"
if not HOOK_PATH.exists():
    HOOK_PATH = TEST_DIR.parent / "oracle_downgrade_warning_gate.py"
spec = importlib.util.spec_from_file_location("oracle_downgrade_warning_gate", HOOK_PATH)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["oracle_downgrade_warning_gate"] = gate
spec.loader.exec_module(gate)


def init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    return tmp_path


def run_hook(payload: dict) -> tuple[int, dict | None]:
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("sys.stdout", stdout):
            code = gate.main()
    output = stdout.getvalue().strip()
    return code, json.loads(output) if output else None


def commit_file(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)


def hook_payload(repo: Path, command: str = "git commit -m change") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": command},
    }


def test_added_skip_warns(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(repo, "tests/test_app.py", "def test_value():\n    assert value == 'expected'\n")
    (repo / "tests" / "test_app.py").write_text(
        "import pytest\n\n@pytest.mark.skip(reason='later')\ndef test_value():\n    assert value == 'expected'\n",
        encoding="utf-8",
    )

    code, output = run_hook(hook_payload(repo))

    assert code == 0
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert "skip-or-xfail-added" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_strong_assertion_weakened_warns(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(repo, "tests/test_app.py", "def test_value():\n    assert result.status == 'active'\n")
    (repo / "tests" / "test_app.py").write_text(
        "def test_value():\n    assert result.status is not None\n",
        encoding="utf-8",
    )

    code, output = run_hook(hook_payload(repo))

    assert code == 0
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "strong-assertion-weakened" in reason


def test_semantic_identity_replaced_by_generated_id_warns(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(
        repo,
        "tests/test_app.py",
        "def test_media_type():\n    assert row.RecordType.DeveloperName == 'Media'\n",
    )
    (repo / "tests" / "test_app.py").write_text(
        "def test_media_type():\n    assert row.RecordTypeId == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )

    code, output = run_hook(hook_payload(repo))

    assert code == 0
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "semantic-identity-to-generated-id" in reason


def test_negative_control_removed_warns(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(
        repo,
        "tests/test_auth.py",
        "def test_rejects_unauthorized_user():\n    assert response.status_code == 403\n",
    )
    (repo / "tests" / "test_auth.py").write_text("", encoding="utf-8")

    code, output = run_hook(hook_payload(repo))

    assert code == 0
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "negative-control-removed" in reason


def test_non_finishing_command_allows_without_warning(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(repo, "tests/test_app.py", "def test_value():\n    assert result.status == 'active'\n")
    (repo / "tests" / "test_app.py").write_text(
        "def test_value():\n    assert result.status is not None\n",
        encoding="utf-8",
    )

    code, output = run_hook(hook_payload(repo, "pytest"))

    assert code == 0
    assert output is None


def test_unrelated_stronger_test_change_allows(tmp_path):
    repo = init_repo(tmp_path)
    commit_file(repo, "tests/test_app.py", "def test_value():\n    assert result is not None\n")
    (repo / "tests" / "test_app.py").write_text(
        "def test_value():\n    assert result.status == 'active'\n",
        encoding="utf-8",
    )

    code, output = run_hook(hook_payload(repo))

    assert code == 0
    assert output is None
