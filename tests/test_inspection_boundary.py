"""Public CLI/hook controls; no inspection executor body is ever evaluated."""
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude/hooks/inspection_boundary.py"


@pytest.fixture
def scope(tmp_path):
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("Cake: measured result is bounded.\n", encoding="utf-8")
    report = tmp_path / "report.md"
    env = dict(os.environ, ESCAPEMENT_INSPECTION_STATE_DIR=str(tmp_path / "state"),
               GATE_SIGNAL_FALLBACK_DIR=str(tmp_path / "signals"),
               BEADS_DIR=str(tmp_path / "no-beads"),
               PYTHONDONTWRITEBYTECODE="1")
    return {"root": tmp_path, "evidence": evidence, "report": report, "env": env}


def cli(scope, *args, ok=True):
    result = subprocess.run([sys.executable, "-B", str(HOOK), *map(str, args)],
                            cwd=scope["root"], env=scope["env"],
                            capture_output=True, text=True, timeout=10)
    if ok:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    return result


def begin(scope, session="parent", limit=24):
    cli(scope, "begin", "--session", session, "--source", scope["evidence"],
        "--artifact", scope["report"], "--max-actions", limit)


def show(scope, session="parent"):
    return json.loads(cli(scope, "show", "--session", session).stdout)


def call(scope, tool, tool_input=None, session="parent", call_id="call", **fields):
    payload = dict(tool_name=tool, tool_input=tool_input or {}, session_id=session,
                   tool_use_id=call_id, cwd=str(scope["root"]), **fields)
    result = subprocess.run([sys.executable, "-B", str(HOOK)],
                            input=json.dumps(payload), cwd=scope["root"],
                            env=scope["env"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else {}


def denied(output):
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    return output["hookSpecificOutput"]


def allowed(output):
    assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


def test_begin_seeds_existing_writer_output_and_reports_canonical_values(scope):
    begin(scope)
    assert scope["report"].is_file() and scope["report"].read_text() == ""
    record = show(scope)
    assert record == dict(version=1, session_id="parent", phase="active",
                          sources=[str(scope["evidence"].resolve())],
                          artifacts=[str(scope["report"].resolve())], max_actions=24,
                          admitted=0, seen_calls=[], rejected=0, report_writes={})
    allowed(call(scope, "read", {"path": str(scope["evidence"]) + ":1-1"}))
    assert show(scope)["admitted"] == 1


@pytest.mark.parametrize("tool", ["Eval", "eval", "bash", "Bash", "python",
    "renamed_interpreter", "mcp__server_evaluate_script", "opaque_alias", "subagent", "Agent"])
def test_execution_opaque_aliases_and_dispatch_are_denied_without_executing(scope, tool):
    begin(scope)
    witness = scope["root"] / "never-executed"
    output = denied(call(scope, tool, {"code": f"open({str(witness)!r}, 'w').write('bad')"}))
    assert not witness.exists()
    assert str(scope["report"]) in output["permissionDecisionReason"]
    assert "unknown" in output["permissionDecisionReason"].lower()
    assert not output.get("inspectionAbort", False)
    assert show(scope)["phase"] == "report"


@pytest.mark.parametrize("writer", ["edit", "mcp__serena_replace_content"])
def test_report_writer_survives_first_deny_without_resetting_abort_count(scope, writer):
    begin(scope)
    denied(call(scope, "Eval"))
    text = "## Findings\nCake measured result is bounded. Comparison with absent source: unknown.\n"
    allowed(call(scope, "write", {"path": str(scope["report"]), "content": text}, call_id="report"))
    # Consumer performs only a write admitted by the public hook.
    scope["report"].write_text(text, encoding="utf-8")
    field = "relative_path" if writer.startswith("mcp__") else "path"
    allowed(call(scope, writer, {field: str(scope["report"]), "oldText": "absent", "newText": "missing"}, call_id="edit"))
    assert "Cake measured result" in scope["report"].read_text()
    assert "unknown" in scope["report"].read_text()
    assert show(scope)["rejected"] == 1
    retry = denied(call(scope, "Eval", call_id="retry"))
    assert retry["inspectionAbort"] is True
    assert show(scope)["rejected"] == 2


@pytest.mark.parametrize("tool,input_kind", [("read", "outside"), ("write", "outside"),
    ("edit", "outside"), ("read", "uri"), ("read", "recursive"),
    ("read", "opaque"), ("mcp__serena_replace_content", "outside")])
def test_outside_paths_recursive_reads_and_opaque_selectors_fail_closed(scope, tool, input_kind):
    begin(scope)
    paths = {"outside": str(scope["root"] / "outside.txt"), "uri": "artifact://opaque",
             "recursive": str(scope["root"] / "**"),
             "opaque": str(scope["evidence"]) + ":unknown-selector"}
    field = "relative_path" if tool.startswith("mcp__") else "path"
    denied(call(scope, tool, {field: paths[input_kind]}))


def test_nominated_directory_is_nonrecursive_and_never_authorizes_descendants(scope):
    cli(scope, "begin", "--session", "parent", "--source", scope["root"],
        "--artifact", scope["report"], "--max-actions", 4)
    allowed(call(scope, "read", {"path": str(scope["root"])}, call_id="listing"))
    denied(call(scope, "read", {"path": str(scope["evidence"])}, call_id="descendant"))


def test_actual_parent_header_shares_counter_and_duplicate_delivery_is_idempotent(scope):
    begin(scope, limit=2)
    parent = scope["root"] / "parent-session.jsonl"
    parent.write_text(json.dumps({"type": "session", "id": "parent"}) + "\n" + "x" * 100000)
    allowed(call(scope, "read", {"path": str(scope["evidence"])}, call_id="one"))
    allowed(call(scope, "read", {"path": str(scope["evidence"])}, session="child", call_id="two", parent_session=str(parent)))
    allowed(call(scope, "read", {"path": str(scope["evidence"])}, session="child", call_id="two", parent_session=str(parent)))
    assert show(scope)["admitted"] == 2
    assert not (scope["root"] / "state/child.json").exists()
    denied(call(scope, "read", {"path": str(scope["evidence"])}, session="child", call_id="three", parent_session=str(parent)))
    cli(scope, "begin", "--session", "parent", "--source", scope["evidence"],
        "--artifact", scope["root"] / "renewal.md", "--max-actions", 48, ok=False)
    assert show(scope)["admitted"] == 2
    denied(call(scope, "bash", session="child", parent_session=str(parent), call_id="retry"))
    assert show(scope)["rejected"] == 2


@pytest.mark.parametrize("binding", ["missing", "not-json", "oversized", "wrong-type"])
def test_explicit_unreadable_or_invalid_parent_cannot_create_fresh_allowance(scope, binding):
    begin(scope)
    parent = scope["root"] / "parent.jsonl"
    if binding == "not-json":
        parent.write_text("not json\n")
    elif binding == "oversized":
        parent.write_text(" " * 70000 + json.dumps({"type": "session", "id": "parent"}))
    elif binding == "wrong-type":
        parent.write_text(json.dumps({"type": "message", "id": "parent"}))
    result = denied(call(scope, "Eval", session="child", parent_session=str(parent)))
    assert "parent" in result["permissionDecisionReason"].lower()
    assert "handoff" in result["permissionDecisionReason"].lower()
    assert not (scope["root"] / "state/child.json").exists()


def test_agent_id_and_environment_do_not_exempt_activated_parent(scope):
    begin(scope)
    scope["env"]["PI_AGENT_ID"] = "child"
    denied(call(scope, "Eval", agent_id="trusted-worker"))
    assert show(scope)["rejected"] == 1


def test_parallel_physical_admissions_serialize_shared_counter(scope):
    begin(scope, limit=3)
    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(lambda i: call(scope, "read", {"path": str(scope["evidence"])}, call_id=f"c{i}"), range(6)))
    assert sum(o.get("hookSpecificOutput", {}).get("permissionDecision") != "deny" for o in outputs) == 3
    assert show(scope)["admitted"] == 3
    assert show(scope)["rejected"] == 3


@pytest.mark.parametrize("args", [[], ["--source", "missing"], ["--max-actions", "0"],
    ["--max-actions", "49"], ["--max-actions", "nan"], ["--session", "../escape"]])
def test_cli_rejects_missing_sources_and_invalid_values_without_seeding(scope, args):
    base = ["begin", "--session", "parent", "--source", str(scope["evidence"]),
            "--artifact", str(scope["report"]), "--max-actions", "24"]
    if not args:
        base = ["begin", "--session", "parent"]
    cli(scope, *base, *args, ok=False)
    assert not scope["report"].exists()


def test_cli_requires_new_artifact_and_existing_parent(scope):
    scope["report"].write_text("Keep existing user report")
    cli(scope, "begin", "--session", "parent", "--source", scope["evidence"],
        "--artifact", scope["report"], "--max-actions", 24, ok=False)
    assert scope["report"].read_text() == "Keep existing user report"
    cli(scope, "begin", "--session", "parent", "--source", scope["evidence"],
        "--artifact", scope["root"] / "missing/report.md", "--max-actions", 24, ok=False)


def test_only_real_external_input_releases_in_place_and_never_renews(scope):
    begin(scope)
    denied(call(scope, "Eval"))
    before = show(scope)
    call(scope, "", hook_event_name="ExternalInput", input_source="synthetic")
    assert show(scope) == before
    cli(scope, "external-input", "--session", "parent", "--source", "synthetic", ok=False)
    call(scope, "", hook_event_name="ExternalInput", input_source="interactive")
    released = show(scope)
    assert released == dict(before, phase="released")
    allowed(call(scope, "Eval", call_id="ordinary"))
    cli(scope, "begin", "--session", "parent", "--source", scope["evidence"],
        "--artifact", scope["root"] / "renewal.md", "--max-actions", 24, ok=False)


def test_rpc_external_cli_release_and_unactivated_session_preserve_ordinary_work(scope):
    allowed(call(scope, "Eval", session="ordinary"))
    begin(scope)
    cli(scope, "external-input", "--session", "parent", "--source", "rpc")
    assert show(scope)["phase"] == "released"
    allowed(call(scope, "bash"))


def test_transition_and_deny_emit_durable_signal(scope):
    begin(scope)
    denied(call(scope, "Eval"))
    logs = list((scope["root"] / "signals").rglob("*.jsonl"))
    records = [json.loads(line) for log in logs for line in log.read_text().splitlines()]
    assert any(r.get("gate") == "inspection_boundary" and r.get("decision") == "deny" for r in records)
    assert any(r.get("gate") == "inspection_boundary" and r.get("decision") == "report" for r in records)


@pytest.mark.parametrize("kind", ["source", "state"])
def test_artifacts_cannot_rewrite_evidence_or_scope_state(scope, kind):
    state = scope["root"] / "state"
    state.mkdir()
    artifact = scope["evidence"] if kind == "source" else state / "parent.json"
    cli(scope, "begin", "--session", "parent", "--source", scope["evidence"],
        "--artifact", artifact, "--max-actions", 24, ok=False)
    assert scope["evidence"].read_text().startswith("Cake:")
    assert not (state / "parent.json").exists()


def test_source_symlink_resolves_but_report_symlink_cannot_escape(scope):
    alias = scope["root"] / "alias.txt"
    alias.symlink_to(scope["evidence"])
    cli(scope, "begin", "--session", "parent", "--source", alias,
        "--artifact", scope["report"], "--max-actions", 24)
    assert show(scope)["sources"] == [str(scope["evidence"].resolve())]
    allowed(call(scope, "read", {"path": str(alias)}, call_id="source-alias"))
    scope["report"].unlink()
    outside = scope["root"] / "outside.md"
    outside.write_text("not report")
    scope["report"].symlink_to(outside)
    denied(call(scope, "write", {"path": str(scope["report"]), "content": "escape"}))
    assert outside.read_text() == "not report"


@pytest.mark.parametrize("phase", ["active", "report"])
def test_stop_handoffs_without_renewal_or_counter_changes(scope, phase):
    begin(scope)
    if phase == "report":
        denied(call(scope, "Eval"))
    before = show(scope)
    result = call(scope, "", hook_event_name="Stop")
    assert result["hookSpecificOutput"] == {"hookEventName": "Stop", "inspectionHandoff": True}
    assert show(scope) == before
    cli(scope, "external-input", "--session", "parent", "--source", "interactive")
    assert call(scope, "", hook_event_name="Stop") == {}
    assert call(scope, "", session="ordinary", hook_event_name="Stop") == {}


def test_missing_parent_repeated_rejection_aborts_without_child_allowance(scope):
    begin(scope)
    missing = str(scope["root"] / "missing-session")
    first = denied(call(scope, "Eval", session="child", parent_session=missing))
    assert not first.get("inspectionAbort", False)
    second = denied(call(scope, "Eval", session="child", parent_session=missing, call_id="retry"))
    assert second["inspectionAbort"] is True
    assert not (scope["root"] / "state/child.json").exists()


def test_recursive_flag_cannot_turn_directory_listing_into_scan(scope):
    cli(scope, "begin", "--session", "parent", "--source", scope["root"],
        "--artifact", scope["report"], "--max-actions", 4)
    denied(call(scope, "read", {"path": str(scope["root"]), "recursive": True}))


def test_report_mutations_have_finite_recovery_with_idempotent_delivery(scope):
    begin(scope)
    inputs = {"path": str(scope["report"]), "content": "## Findings\nUseful finding; comparison unknown.\n"}
    allowed(call(scope, "write", inputs, call_id="one"))
    allowed(call(scope, "write", inputs, call_id="one"))
    assert show(scope)["report_writes"] == {str(scope["report"]): 1}
    allowed(call(scope, "write", inputs, call_id="two"))
    third = denied(call(scope, "write", inputs, call_id="three"))
    assert third["inspectionAbort"] is True
    assert show(scope)["report_writes"] == {str(scope["report"]): 2}


def test_artifact_reads_use_shared_allowance_after_denial(scope):
    begin(scope, limit=1)
    denied(call(scope, "Eval"))
    allowed(call(scope, "read", {"path": str(scope["report"])}, call_id="report-read"))
    assert show(scope)["admitted"] == 1
    denied(call(scope, "read", {"path": str(scope["report"])}, call_id="report-read-again"))


def test_records_without_report_writes_default_to_empty_compatibly(scope):
    begin(scope)
    path = scope["root"] / "state/parent.json"
    original = json.loads(path.read_text())
    original.pop("report_writes")
    path.write_text(json.dumps(original))
    allowed(call(scope, "write", {"path": str(scope["report"]), "content": "finding"}, call_id="report"))
    assert show(scope)["report_writes"] == {str(scope["report"]): 1}


@pytest.mark.parametrize("kind,count", [("source", 33), ("artifact", 5)])
def test_cli_scope_lists_are_finite_before_seeding(scope, kind, count):
    args = ["begin", "--session", "parent", "--source", str(scope["evidence"]),
            "--artifact", str(scope["report"])]
    args += [value for _ in range(count) for value in
             (f"--{kind}", str(scope["evidence"] if kind == "source" else scope["report"]))]
    cli(scope, *args, ok=False)
    assert not scope["report"].exists()


def test_oversized_record_fails_closed_without_loading_transcript_sized_state(scope):
    begin(scope)
    path = scope["root"] / "state/parent.json"
    path.write_text(" " * (256 * 1024 + 1) + path.read_text())
    denied(call(scope, "Eval"))
