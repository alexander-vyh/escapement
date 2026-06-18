import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
HOOK_PATH = TEST_DIR / "implementation_echo_test_gate.py"
if not HOOK_PATH.exists():
    HOOK_PATH = TEST_DIR.parent / "implementation_echo_test_gate.py"
spec = importlib.util.spec_from_file_location("implementation_echo_test_gate", HOOK_PATH)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["implementation_echo_test_gate"] = gate
spec.loader.exec_module(gate)


def init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


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
    """Assert the deny was honored EXACTLY ONCE via the canonical mechanism: a
    single permissionDecision="deny" JSON document on stdout AND exit code 0
    (NOT exit 2). A deny JSON *plus* exit 2 is a contradictory double-block;
    asserting exit 0 rejects that shape.
    """
    assert code == 0, (
        "deny is carried by the stdout JSON decision, not exit 2 — "
        "permissionDecision=deny plus exit 2 is a contradictory double-block"
    )
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_shared_generated_literal_detected():
    source = {"src/app.py": "MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n"}
    tests = {"tests/test_app.py": "def test_media():\n    assert id == '0124p000000ABCDEF1'\n"}

    issues = gate.find_shared_generated_literals(source, tests)

    assert len(issues) == 1
    assert issues[0].kind == "shared-generated-literal"


def test_shared_semantic_literal_not_detected():
    source = {"src/app.py": "MEDIA = 'Media'\n"}
    tests = {"tests/test_app.py": "def test_media():\n    assert row.type == 'Media'\n"}

    assert gate.find_shared_generated_literals(source, tests) == []


def test_python_mock_only_test_detected():
    text = """
def test_sync_calls_client(client):
    sync(client)
    client.send.assert_called_once_with('abc')
"""

    issues = gate.find_python_mock_only_tests("tests/test_sync.py", text)

    assert len(issues) == 1
    assert issues[0].kind == "mock-only-test"


def test_python_mock_plus_outcome_allowed():
    text = """
def test_sync_persists_status(client, repo):
    sync(client, repo)
    client.send.assert_called_once()
    assert repo.status == 'synced'
"""

    assert gate.find_python_mock_only_tests("tests/test_sync.py", text) == []


def test_python_def_inside_string_literal_not_flagged():
    """A test-shaped pattern inside a string literal is a fixture, not a test.

    Pattern-detector hooks have test files whose whole job is to feed example
    bad-test code (as string fixtures) to the detector. The gate must not
    mistake those fixtures for real tests in the file being scanned.
    """
    text = '''
EXAMPLE_BAD_TEST = """
def test_sync_calls_client(client):
    sync(client)
    client.send.assert_called_once_with('abc')
"""


def test_real_one():
    result = compute(2)
    assert result == 4
'''

    # Only test_real_one is a real function, and it has an outcome assertion.
    # The mock-only pattern lives inside EXAMPLE_BAD_TEST and must be ignored.
    assert gate.find_python_mock_only_tests("tests/test_thing.py", text) == []


def test_js_mock_only_test_detected():
    text = """
it('sends the event', () => {
  const send = vi.fn()
  run(send)
  expect(send).toHaveBeenCalledWith('event')
})
"""

    issues = gate.find_js_mock_only_tests("src/app.test.ts", text)

    assert len(issues) == 1
    assert issues[0].kind == "mock-only-test"


def test_js_mock_plus_outcome_allowed():
    text = """
it('saves the event', () => {
  const send = vi.fn()
  const result = run(send)
  expect(send).toHaveBeenCalledWith('event')
  expect(result.status).toBe('saved')
})
"""

    assert gate.find_js_mock_only_tests("src/app.test.ts", text) == []


def test_commit_blocks_shared_generated_literal(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_media_filter():\n    assert record_type_id == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "IMPLEMENTATION-ECHO TEST GATE" in reason
    assert "shared-generated-literal" in reason


def test_codex_implementation_echo_test_gate_blocks_shared_generated_literal(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_media_filter():\n    assert record_type_id == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "IMPLEMENTATION-ECHO TEST GATE" in reason
    assert "shared-generated-literal" in reason


def test_commit_denies_when_oracle_override_is_circular(tmp_path):
    """A flagged file whose `# oracle:` reason only restates its own asserted
    literal is NOT exempted — the gate still denies and explains the rejection.
    This is the substance bar: presence of a reason is not enough.
    """
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "# oracle: the 0124p000000ABCDEF1 literal is the asserted oracle value\n"
        "def test_media_filter():\n"
        "    assert record_type_id == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "REJECTED" in reason
    assert "circular" in reason


def test_commit_allows_when_oracle_override_is_independent(tmp_path):
    """A flagged file whose `# oracle:` reason names an INDEPENDENT source of
    truth (tokens outside the file's own asserted literals) is exempted.
    The escape path stays usable for legitimate overrides.
    """
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "# oracle: cross-checked against the upstream Salesforce media report export totals\n"
        "def test_media_filter():\n"
        "    assert record_type_id == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None


def test_commit_blocks_magic_number_echo(tmp_path):
    """The 91% shape end-to-end: a test asserting a formatted number that lives
    in a source description string is denied as a magic-number-echo.
    """
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "metric_descriptions.py").write_text(
        'PCT_AUTOMATED = "all-history snapshot reads ~91% because it carries older grants"\n',
        encoding="utf-8",
    )
    (repo / "tests" / "test_metrics.py").write_text(
        'def test_pct():\n    assert "91%" in describe("dw_x", "pct_automated")\n',
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "magic-number-echo" in reason
    assert "91%" in reason


def test_commit_allows_bare_int_constant_assertion(tmp_path):
    """Negative control: a legitimate constant assertion (bare ints, no string)
    must NOT be flagged — this is what distinguishes the detector from a
    flag-every-shared-number fragile implementation.
    """
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "score.py").write_text("PASS_THRESHOLD = 91\n", encoding="utf-8")
    (repo / "tests" / "test_score.py").write_text(
        "def test_pass():\n    assert score == 91\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git commit -m change"},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None


def test_non_finishing_command_allows_even_with_issue(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("MEDIA_RECORD_TYPE_ID = '0124p000000ABCDEF1'\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_media_filter():\n    assert record_type_id == '0124p000000ABCDEF1'\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "pytest"},
    }

    code, output = run_hook(payload)

    assert code == 0
    assert output is None
