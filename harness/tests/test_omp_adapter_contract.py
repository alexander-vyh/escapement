"""Architecture checks for the pinned, sterile OMP SDK boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "harness" / "bin" / "omp_role_adapter.ts"
sys.path.insert(0, str(REPO / "harness" / "bin"))

from omp_role_invocation import _snapshot_adapter, validate_omp_adapter_source  # noqa: E402


def test_omp_dependency_is_exactly_pinned() -> None:
    package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))

    assert package["devDependencies"] == {
        "@oh-my-pi/pi-coding-agent": "18.1.4",
    }
    assert (REPO / "bun.lock").is_file()


def test_adapter_explicitly_removes_ambient_and_agentic_surfaces() -> None:
    source = ADAPTER.read_text(encoding="utf-8")

    required_fragments = {
        "Settings.isolated({",
        '"advisor.enabled": false',
        '"retry.enabled": false',
        '"retry.modelFallback": false',
        '"retry.usageAwareFallback": false',
        '"compaction.enabled": false',
        '"compaction.idleEnabled": false',
        '"memory.backend": "off"',
        '"autolearn.enabled": false',
        '"goal.enabled": false',
        '"todo.enabled": false',
        '"magicKeywords.enabled": false',
        '"recap.enabled": false',
        '"title.refreshOnReplan": false',
        "includeWorkspaceTree: false",
        "SessionManager.inMemory(request.cwd)",
        "new AgentRegistry()",
        "skills: []",
        "rules: []",
        "contextFiles: []",
        "promptTemplates: []",
        "slashCommands: []",
        "disableExtensionDiscovery: true",
        "enableMCP: false",
        "enableLsp: false",
        "enableIrc: false",
        'spawns: ""',
        "toolNames: []",
        "restrictToolNames: true",
        "requireYieldTool: false",
        "hasUI: false",
        "interactivePrompts: false",
        "autoApprove: false",
        "expandPromptTemplates: false",
        "synthetic: true",
        "userInitiated: false",
    }
    for fragment in required_fragments:
        assert fragment in source


def test_adapter_has_no_task_advisor_or_completion_authority_import() -> None:
    source = ADAPTER.read_text(encoding="utf-8")

    forbidden = ("/task/", "advisor", "verified_outcome", "CompletionReceipt")
    import_lines = [line for line in source.splitlines() if line.startswith("import ")]
    assert all(fragment not in line for line in import_lines for fragment in forbidden)


@pytest.mark.parametrize(
    "mutant",
    (
        '\nsettings.override("retry.enabled", true);\n',
        "\ncreateAgentSession({});\n",
        '\nimport("advisor-bypass");\n',
        '\nfetch("https://provider.example");\n',
        "\nconst capturedEvents = []; capturedEvents.push({});\n",
    ),
)
def test_runtime_preflight_rejects_named_isolation_mutants(
    tmp_path: Path, mutant: str
) -> None:
    changed = tmp_path / "mutated-adapter.ts"
    changed.write_text(ADAPTER.read_text(encoding="utf-8") + mutant, encoding="utf-8")

    with pytest.raises(ValueError):
        validate_omp_adapter_source(changed)


def test_runtime_preflight_accepts_pinned_adapter_and_returns_source_digest() -> None:
    digest = validate_omp_adapter_source(ADAPTER)

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_snapshot_executes_private_immutable_copy_not_mutable_source(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "harness" / "bin" / "adapter.ts"
    source.parent.mkdir(parents=True)
    (repo / "node_modules").mkdir()
    source.write_bytes(b"reviewed adapter bytes\n")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    snapshot = _snapshot_adapter(source, expected)
    try:
        source.write_bytes(b"replacement after validation\n")
        assert snapshot != source
        assert snapshot.read_bytes() == b"reviewed adapter bytes\n"
        assert snapshot.stat().st_mode & 0o777 == 0o400
        assert repo / "node_modules" in snapshot.parents
    finally:
        snapshot.chmod(0o600)
        snapshot.unlink(missing_ok=True)


def test_pinned_adapter_loads_under_installed_bun_without_import_errors() -> None:
    bun = shutil.which("bun")
    assert bun is not None

    completed = subprocess.run(
        (bun, str(ADAPTER)),
        input="{}",
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "request schema is invalid" in completed.stderr
    assert "Export named" not in completed.stderr
