"""Behavioral inspection oracle at the rendered Pi physical admission seam.

Public records are authored here, independently of the boundary implementation.
The carrier never executes submitted code: an admitted executor creates a small
witness instead. The recorded incident program is inert input, not a smoke scan.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run


# Recorded Cake Eval argument, 2026-10-09T01:32:42.955Z. Inert replay only.
INCIDENT_CODE = r"""raw_registry=subprocess.run(['git','worktree','list','--porcelain','-z'],cwd=value_repo,env=value_env,capture_output=True,text=True,timeout=30)
value_registered=[]
for block in raw_registry.stdout.split('\0\0'):
    data={}
    for field in block.split('\0'):
        key,_,val=field.partition(' ')
        if key: data[key]=val or True
    if 'worktree' in data: value_registered.append(data)
research_errors=[]
def research_metadata(w):
    base=pathlib.Path(w['worktree']); folder=base/'.research'; info={'worktree':str(base),'research_directory':link_info(folder,base),'files':[],'errors':[]}
    if not os.path.lexists(folder) or folder.is_symlink(): return info
    listing=value_git(base,['ls-files','--others','--ignored','--exclude-standard','-z','--','.research'])
    if listing['returncode']: info['errors'].append(listing['stderr']); return info
    for name in listing['paths']:
        path=base/name
        if path.is_relative_to(value_dir): continue
        try:
            st=path.lstat(); record={'path':str(path),'relative_path':name,'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'type':'symlink' if stat.S_ISLNK(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'other'}
            if record['type']=='symlink': record['resolved_path']=str(path.resolve())
            elif record['type']=='file' and st.st_size<=50*1024*1024:
                record['sha256']=hashlib.sha256(path.read_bytes()).hexdigest(); after=path.stat(); record['stable_during_hash']=after.st_size==st.st_size and after.st_mtime_ns==st.st_mtime_ns
            elif record['type']=='file': record['hash_limit']='Over50MiB; not compared'
            info['files'].append(record)
        except OSError as exc: info['errors'].append(name+': '+str(exc))
    return info
all_research=list(ThreadPoolExecutor(max_workers=6).map(research_metadata,value_registered))
research_by_hash={}
for tree in all_research:
    for f in tree['files']:
        if f.get('sha256') and f.get('stable_during_hash'): research_by_hash.setdefault(f['sha256'],[]).append(f['path'])
value_candidate_paths={w['path'] for w in value_candidates}
shortlist_research=[]
for tree in all_research:
    if tree['worktree'] not in value_candidate_paths: continue
    for f in tree['files']:
        if f.get('sha256'): f['identical_copies_elsewhere']=[p for p in research_by_hash.get(f['sha256'],[]) if p!=f['path']]
    shortlist_research.append(tree)
research_input={'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'registered_worktrees_scanned':len(value_registered),'comparison_paths':'Root plus all registered .research directories; regularfiles up to50MiB, no symlink recursion','worktrees':shortlist_research,'comparison_errors':[{'worktree':t['worktree'],'errors':t['errors']} for t in all_research if t['errors']],'all_research_file_count':sum(len(t['files']) for t in all_research)}
write(str(value_dir/'research-hash-inventory.json'),json.dumps(research_input,indent=2)+'\n')
print('Research hash inventory written:',len(value_registered),'registrations,',research_input['all_research_file_count'],'research files across comparison set,',sum(len(t['files']) for t in shortlist_research),'shortlist files,',len(research_input['comparison_errors']),'directory errors.')
external_dependents=[]
for wt in value_registered:
    base=pathlib.Path(wt['worktree'])
    for name in ['.env','.venv','.beads','.research']:
        p=base/name
        if p.is_symlink():
            target=p.resolve()
            for candidate in value_candidates:
                if target.is_relative_to(pathlib.Path(candidate['path'])) and wt['worktree']!=candidate['path']:
                    external_dependents.append({'dependent_worktree':str(base),'link':str(p),'target':str(target),'target_candidate':candidate['name'],'dependent_is_candidate':str(base) in value_candidate_paths})
write(str(value_dir/'external-link-dependents.json'),json.dumps({'registered_worktrees':len(value_registered),'dependents':external_dependents},indent=2)+'\n')
print('Cross-worktree symlinks into candidates:',len(external_dependents))"""


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


@pytest.fixture
def inspection(tmp_path):
    repo = git_repo(tmp_path / "repo", {
        ".gitignore": ".research/\n",
        "evidence.md": "Useful finding: the candidate preserves invoice provenance.\nNo cross-worktree comparison was performed.\n",
        "outside.md": "Unnominated evidence must not be acquired.\n",
        "src/app.py": "VALUE = 1\n",
        ".beads/.gitkeep": "",
    })
    session = Session(repo)
    env = pi_env(tmp_path)
    state_dir = tmp_path / "inspection-state"
    state_dir.mkdir()
    env["ESCAPEMENT_INSPECTION_STATE_DIR"] = str(state_dir)
    report = (repo / ".research" / "bounded-report.md").resolve()
    report.parent.mkdir()
    report.write_text("", encoding="utf-8")
    source = (repo / "evidence.md").resolve()
    record = {
        "version": 1, "session_id": session.id, "phase": "active",
        "sources": [str(source.resolve())], "artifacts": [str(report.resolve())],
        "max_actions": 3, "admitted": 0, "seen_calls": [], "rejected": 0,
    }
    state = state_dir / f"{session.id}.json"
    state.write_text(json.dumps(record), encoding="utf-8")
    return session, env, source, report, state


def witness_call(session, tool, arguments, path):
    event = session.tool_call(tool, arguments)
    event["executor"] = {"kind": "witness", "path": str(path), "content": "executor reached\n"}
    event["observeAbort"] = True
    return event


def assert_inspection_denied(outcome, report):
    decision = outcome["result"]
    assert decision and decision["block"] is True, outcome
    assert str(report) in decision["reason"], decision
    assert "unknown" in decision["reason"].lower(), decision


@pytest.mark.parametrize("tool,arguments", [
    pytest.param("eval", {"language": "py", "code": INCIDENT_CODE,
                          "title": "Comparing unique evidence across worktrees",
                          "timeout": 180, "reset": False}, id="recorded-native-eval"),
    pytest.param("opaque_compute_73", {"request": "compare everything"}, id="unknown-opaque-alias"),
    pytest.param("renamed_interpreter_19", {"language": "py", "code": "print('tiny harmless label')"}, id="renamed-interpreter"),
    pytest.param("mcpScript", {"code": "return tools[computedName](arguments);"}, id="computed-mcp-script"),
    pytest.param("workflowScript", {"code": "return runs.run(computedName, request);"}, id="dynamic-delegation"),
    pytest.param("bash", {"command": "python3 -c \"print('bounded-looking')\""}, id="shell-interpreter"),
])
def test_strict_inspection_denies_execution_before_executor_witness(plugin, inspection, tmp_path, tool, arguments):
    session, env, source, report, state = inspection
    witness = tmp_path / "executor-witness.txt"
    [outcome] = run(plugin, [witness_call(session, tool, arguments, witness)], env)
    assert_inspection_denied(outcome, report)
    assert not witness.exists(), "A denied optional inspection reached its executor"
    assert outcome["aborts"] == 0, "First denial must preserve the report opportunity"
    record = json.loads(state.read_text(encoding="utf-8"))
    assert record["phase"] == "report"
    assert record["rejected"] == 1
    assert record["admitted"] == 0


def read_call(session, source):
    event = session.tool_call("read", {"path": f"{source}:1-1"})
    event["executor"] = {"kind": "read", "path": str(source), "start": 1, "end": 1}
    return event


def write_call(session, report, content):
    event = session.tool_call("write", {"path": str(report), "content": content})
    event["executor"] = {"kind": "write", "path": str(report), "content": content}
    return event


def test_nominated_evidence_and_exact_report_remain_useful_after_denial(plugin, inspection, tmp_path):
    session, env, source, report, state = inspection
    [read] = run(plugin, [read_call(session, source)], env)
    assert read["result"] is None, read
    assert read["read"] == "Useful finding: the candidate preserves invoice provenance."
    witness = tmp_path / "global-comparison-witness"
    [denied] = run(plugin, [witness_call(session, "eval", {"language": "py", "code": INCIDENT_CODE}, witness)], env)
    assert_inspection_denied(denied, report)
    content = (
        "# Bounded inspection\n\n## Findings\n"
        + read["read"]
        + "\n\nCross-worktree uniqueness: unknown; the global comparison was not performed.\n"
    )
    [written] = run(plugin, [write_call(session, report, content)], env)
    assert written["result"] is None, written
    assert written["executed"] is True
    assert report.read_text(encoding="utf-8") == (
        "# Bounded inspection\n\n## Findings\n"
        "Useful finding: the candidate preserves invoice provenance.\n\n"
        "Cross-worktree uniqueness: unknown; the global comparison was not performed.\n"
    )
    assert not witness.exists()
    assert json.loads(state.read_text(encoding="utf-8"))["rejected"] == 1


def test_seeded_existing_file_writer_can_persist_read_only_child_report(plugin, inspection, tmp_path):
    session, env, source, report, state = inspection
    parent_file = tmp_path / "actual-parent.jsonl"
    parent_file.write_text(json.dumps(session.header) + "\n", encoding="utf-8")
    child = Session(Path(session.cwd), parent_session=str(parent_file))
    [read] = run(plugin, [read_call(child, source)], env)
    assert read["result"] is None, read
    assert read["read"] == "Useful finding: the candidate preserves invoice provenance."
    report.write_text("# Findings\nPending bounded handoff.\n", encoding="utf-8")
    content = "# Findings\n" + read["read"] + "\nComparison: unknown.\n"
    arguments = {"relative_path": str(report), "needle": "Pending bounded handoff.",
                 "repl": read["read"] + "\nComparison: unknown.", "mode": "literal"}
    event = child.tool_call("mcp__serena_replace_content", arguments)
    event["executor"] = {"kind": "replace", "path": str(report),
                         "before": arguments["needle"], "after": arguments["repl"]}
    [written] = run(plugin, [event], env)
    assert written["result"] is None, written
    assert written["executed"] is True
    assert report.read_text(encoding="utf-8") == content
    assert json.loads(state.read_text(encoding="utf-8"))["admitted"] > 0


@pytest.mark.parametrize("route", ["outside-read", "uri-read", "wrong-report-write", "recursive-list", "delegate"])
def test_non_nominated_effects_are_blocked_before_executor(plugin, inspection, tmp_path, route):
    session, env, source, report, state = inspection
    other_report = report.with_name("unapproved.md")
    requests = {
        "outside-read": ("read", {"path": str(Path(session.cwd) / "outside.md")}),
        "uri-read": ("read", {"path": "xd://opaque-tool-device"}),
        "wrong-report-write": ("write", {"path": str(other_report), "content": "silently widen output"}),
        "recursive-list": ("glob", {"path": str(Path(session.cwd) / "**" / "*")}),
        "delegate": ("subagent", {"agent": "scout", "task": "compare the whole worktree registry"}),
    }
    tool, arguments = requests[route]
    witness = tmp_path / "forbidden-effect"
    [outcome] = run(plugin, [witness_call(session, tool, arguments, witness)], env)
    assert_inspection_denied(outcome, report)
    assert not witness.exists()
    assert not other_report.exists()


def test_real_parent_child_share_allowance_across_extension_reloads(plugin, inspection, tmp_path):
    parent, env, source, report, state = inspection
    record = json.loads(state.read_text(encoding="utf-8"))
    record["max_actions"] = 2
    state.write_text(json.dumps(record), encoding="utf-8")
    parent_file = tmp_path / "actual-parent.jsonl"
    # Header id, not the filename, identifies the parent's public record.
    parent_file.write_text(json.dumps(parent.header) + "\n", encoding="utf-8")
    child = Session(Path(parent.cwd), parent_session=str(parent_file))
    parent_read = read_call(parent, source)
    parent_read["payload"]["toolCallId"] = "parent-evidence-1"
    [first] = run(plugin, [parent_read], env)
    child_read = read_call(child, source)
    child_read["payload"]["toolCallId"] = "child-evidence-1"
    [second] = run(plugin, [child_read], env)
    assert first["read"] == second["read"] == "Useful finding: the candidate preserves invoice provenance."
    assert first["result"] is second["result"] is None
    assert json.loads(state.read_text(encoding="utf-8"))["admitted"] == 2
    [exhausted] = run(plugin, [read_call(parent, source)], env)
    assert_inspection_denied(exhausted, report)
    assert "read" not in exhausted, "An exhausted scope still acquired evidence"
    child_state = state.parent / f"{child.id}.json"
    assert not child_state.exists(), "A child was issued an independent allowance"
    [handoff] = run(plugin, [write_call(child, report, "# Findings\nInvoice provenance retained.\nComparison: unknown.\n")], env)
    assert handoff["result"] is None, handoff
    assert report.read_text(encoding="utf-8") == "# Findings\nInvoice provenance retained.\nComparison: unknown.\n"
    final = json.loads(state.read_text(encoding="utf-8"))
    assert final["admitted"] == 2
    assert final["phase"] == "report"


def test_unreadable_explicit_parent_binding_fails_closed(plugin, inspection, tmp_path):
    parent, env, source, report, state = inspection
    child = Session(Path(parent.cwd), parent_session=str(tmp_path / "missing-parent.jsonl"))
    witness = tmp_path / "unbound-child-executor"
    [outcome] = run(plugin, [witness_call(child, "eval", {"language": "py", "code": "print('child')"}, witness)], env)
    decision = outcome["result"]
    assert decision and decision["block"] is True, outcome
    assert "parent" in decision["reason"].lower()
    assert any(word in decision["reason"].lower() for word in ("report", "handoff"))
    assert not witness.exists()


def test_second_rejection_aborts_without_follow_up_or_allowance_reset(plugin, inspection, tmp_path):
    session, env, source, report, state = inspection
    first_witness, second_witness = tmp_path / "first", tmp_path / "second"
    report_content = "# Findings\nOptional comparison: unknown.\n"
    outcomes = run(plugin, [
        witness_call(session, "opaque_first", {"code": "first"}, first_witness),
        write_call(session, report, report_content),
        witness_call(session, "opaque_retry", {"code": "retry"}, second_witness),
    ], env)
    first, written, second = outcomes
    assert_inspection_denied(first, report)
    assert_inspection_denied(second, report)
    assert first["aborts"] == 0
    assert second["aborts"] == 1, "Second rejection must invoke documented context.abort()"
    assert written["result"] is None
    assert report.read_text(encoding="utf-8") == report_content
    assert not first_witness.exists() and not second_witness.exists()
    assert not [message for outcome in outcomes for message in outcome["sent"] if message["kind"] == "user"], (
        "Rejection must not schedule another synthetic follow-up turn"
    )
    final = json.loads(state.read_text(encoding="utf-8"))
    assert final["rejected"] == 2
    assert final["admitted"] == 0
    assert final["phase"] == "report"


@pytest.mark.parametrize("input_source", ["interactive", "rpc"])
def test_only_external_user_input_releases_scope_preserving_history(plugin, inspection, tmp_path, input_source):
    session, env, source, report, state = inspection
    rejected_witness = tmp_path / "rejected"
    [first] = run(plugin, [witness_call(session, "eval", {"code": "inspect"}, rejected_witness)], env)
    assert_inspection_denied(first, report)
    before = json.loads(state.read_text(encoding="utf-8"))
    synthetic = session.prompt("Synthetic continuation: complete the optional comparison.")
    [prompt] = run(plugin, [synthetic], env)
    assert json.loads(state.read_text(encoding="utf-8")) == before, prompt
    after_synthetic = tmp_path / "synthetic-executor"
    [still_denied] = run(plugin, [witness_call(session, "renamed_eval", {"code": "inspect"}, after_synthetic)], env)
    assert_inspection_denied(still_denied, report)
    assert still_denied["aborts"] == 1
    history = json.loads(state.read_text(encoding="utf-8"))
    external = session._event("input", {
        "type": "input", "text": "Now implement the approved repair.",
        "images": [], "source": input_source,
    })
    [released_input] = run(plugin, [external], env)
    released = json.loads(state.read_text(encoding="utf-8"))
    assert released["phase"] == "released", released_input
    for field in ("session_id", "sources", "artifacts", "max_actions", "admitted", "seen_calls", "rejected"):
        assert released[field] == history[field], f"Release destroyed historical {field}"
    ordinary_witness = tmp_path / "ordinary-implementation"
    [ordinary] = run(plugin, [witness_call(session, "eval", {"language": "py", "code": "approved repair"}, ordinary_witness)], env)
    assert ordinary["result"] is None, ordinary
    assert ordinary_witness.read_text(encoding="utf-8") == "executor reached\n"
    assert not rejected_witness.exists() and not after_synthetic.exists()


def test_unactivated_session_keeps_ordinary_execution_usable(plugin, tmp_path):
    repo = git_repo(tmp_path / "repo", {"README.md": "Normal implementation.\n"})
    session = Session(repo)
    env = pi_env(tmp_path)
    env["ESCAPEMENT_INSPECTION_STATE_DIR"] = str(tmp_path / "unused-inspection-state")
    witness = tmp_path / "normal-executor"
    [outcome] = run(plugin, [witness_call(session, "eval", {"language": "py", "code": "ordinary implementation"}, witness)], env)
    assert outcome["result"] is None, outcome
    assert outcome["aborts"] == 0
    assert witness.read_text(encoding="utf-8") == "executor reached\n"


@pytest.mark.parametrize("input_source", ["interactive", "rpc"])
def test_real_pi_sdk_admits_evidence_blocks_native_executor_and_releases_on_input(plugin, tmp_path, input_source):
    """Real SDK carrier; no provider call and no submitted program execution."""
    pi = shutil.which("pi")
    assert pi, "Installed Pi CLI is required for the real-host admission oracle"
    sdk = Path(pi).resolve().with_name("index.js")
    assert sdk.is_file(), "The selected Pi installation must provide its SDK"
    package = tmp_path / "package"
    package.mkdir()
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / "package.json", package / "package.json")
    shutil.copytree(plugin, package / "plugins" / "escapement-pi")
    repo = git_repo(tmp_path / "repo", {
        ".gitignore": ".research/\n",
        "evidence.md": "Useful finding: the candidate preserves invoice provenance.\n",
    })
    source = (repo / "evidence.md").resolve()
    report = (repo / ".research" / "sdk-report.md").resolve()
    report.parent.mkdir()
    report.write_text("", encoding="utf-8")
    state_dir = tmp_path / "inspection-state"
    state_dir.mkdir()
    agent_dir = tmp_path / "pi-agent"
    env = pi_env(tmp_path)
    env.update({"PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1",
                "ESCAPEMENT_INSPECTION_STATE_DIR": str(state_dir)})
    installed = subprocess.run(
        [pi, "install", str(package), "--approve"], cwd=repo, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert installed.returncode == 0, installed.stderr
    probe = tmp_path / "sdk-inspection.mjs"
    probe.write_text(r"""
import fs from "node:fs/promises";
const { createAgentSession } = await import(process.argv[2]);
const [agentDir, cwd, source, report, stateDir, inputSource, incident] = process.argv.slice(3);
const created = await createAgentSession({ agentDir, cwd, noTools: "all" });
const { session, extensionsResult } = created;
const statePath = `${stateDir}/${session.sessionManager.getSessionId()}.json`;
await fs.writeFile(statePath, JSON.stringify({
  version: 1, session_id: session.sessionManager.getSessionId(), phase: "active",
  sources: [source], artifacts: [report], max_actions: 3,
  admitted: 0, seen_calls: [], rejected: 0,
}));
let aborts = 0;
const originalAbort = session.abort.bind(session);
session.abort = async () => { aborts += 1; await originalAbort(); };
const followUps = [];
session.sendUserMessage = async (text, options) => { followUps.push({ text, options }); };
let serial = 0;
async function dispatch(name, args, execute) {
  const id = `sdk-call-${++serial}`;
  const result = (await session.agent.beforeToolCall({
    toolCall: { type: "toolCall", id, name, arguments: args }, args,
  })) ?? null;
  if (!result?.block && execute) await execute();
  return result;
}
let acquired = null;
const read = await dispatch("read", { path: source }, async () => {
  acquired = await fs.readFile(source, "utf8");
});
const denied = await dispatch("eval", {
  language: "py", code: incident, title: "Comparing unique evidence across worktrees",
  timeout: 180, reset: false,
}, async () => { await fs.writeFile(`${cwd}/native-witness`, "executor reached\n"); });
const reportText = `# Findings\n${acquired}\nCross-worktree uniqueness: unknown; comparison was not performed.\n`;
const written = await dispatch("write", { path: report, content: reportText }, async () => {
  await fs.writeFile(report, reportText);
});
const beforeSynthetic = JSON.parse(await fs.readFile(statePath, "utf8"));
await session.extensionRunner.emitBeforeAgentStart("Synthetic continuation.", undefined, "BASE");
const afterSynthetic = JSON.parse(await fs.readFile(statePath, "utf8"));
const second = await dispatch("renamed_opaque_eval", { code: "harmless-looking alias" }, async () => {
  await fs.writeFile(`${cwd}/alias-witness`, "executor reached\n");
});
const beforeExternal = JSON.parse(await fs.readFile(statePath, "utf8"));
await session.extensionRunner.emitInput("Implement the approved repair.", undefined, inputSource);
const afterExternal = JSON.parse(await fs.readFile(statePath, "utf8"));
const normal = await dispatch("eval", { language: "py", code: "ordinary repair" }, async () => {
  await fs.writeFile(`${cwd}/normal-witness`, "executor reached\n");
});
console.log(JSON.stringify({
  errors: extensionsResult.errors,
  extensions: extensionsResult.extensions.map(item => item.resolvedPath),
  read, acquired, denied, written, second, normal, aborts, followUps,
  beforeSynthetic, afterSynthetic, beforeExternal, afterExternal,
}));
""", encoding="utf-8")
    completed = subprocess.run(
        ["node", str(probe), str(sdk), str(agent_dir), str(repo), str(source),
         str(report), str(state_dir), input_source, INCIDENT_CODE],
        cwd=repo, env=env, capture_output=True, text=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["errors"] == []
    assert result["extensions"] == [str(package / "plugins" / "escapement-pi" / "extensions" / "index.ts")]
    assert result["read"] is None
    assert result["acquired"] == "Useful finding: the candidate preserves invoice provenance.\n"
    for key in ("denied", "second"):
        assert result[key] and result[key]["block"] is True, result
        assert str(report) in result[key]["reason"]
        assert "unknown" in result[key]["reason"].lower()
    assert not (repo / "native-witness").exists()
    assert not (repo / "alias-witness").exists()
    assert result["written"] is None
    assert report.read_text(encoding="utf-8") == (
        "# Findings\nUseful finding: the candidate preserves invoice provenance.\n\n"
        "Cross-worktree uniqueness: unknown; comparison was not performed.\n"
    )
    assert result["beforeSynthetic"] == result["afterSynthetic"]
    assert result["aborts"] == 1
    assert result["followUps"] == []
    assert result["afterExternal"]["phase"] == "released"
    for field in ("session_id", "sources", "artifacts", "max_actions", "admitted", "seen_calls", "rejected"):
        assert result["afterExternal"][field] == result["beforeExternal"][field]
    assert result["normal"] is None
    assert (repo / "normal-witness").read_text(encoding="utf-8") == "executor reached\n"


def prior_undeclared_change(session):
    """A pre-inspection change that ordinarily makes Pi request continuation."""
    target = Path(session.cwd) / "src" / "app.py"
    session.user("Make VALUE configurable.")
    arguments = {"path": str(target), "content": "VALUE = 2\n"}
    session.tool_call("write", arguments)
    target.write_text(arguments["content"], encoding="utf-8")
    session.tool_result("write", arguments, "Wrote src/app.py")


@pytest.mark.parametrize("boundary", ["active", "denied", "exhausted"])
def test_inspection_handoff_does_not_restart_optional_work_after_extension_reload(plugin, inspection, tmp_path, boundary):
    session, env, source, report, state = inspection
    prior_undeclared_change(session)
    if boundary == "denied":
        [denied] = run(plugin, [witness_call(session, "eval", {"code": "optional comparison"}, tmp_path / "optional-witness")], env)
        assert_inspection_denied(denied, report)
    elif boundary == "exhausted":
        record = json.loads(state.read_text(encoding="utf-8"))
        record["max_actions"] = 1
        state.write_text(json.dumps(record), encoding="utf-8")
        [read] = run(plugin, [read_call(session, source)], env)
        assert read["read"] == "Useful finding: the candidate preserves invoice provenance."
        [denied] = run(plugin, [read_call(session, source)], env)
        assert_inspection_denied(denied, report)
        assert "read" not in denied
    report_content = "# Findings\nInvoice provenance retained.\nCross-worktree uniqueness: unknown.\n"
    [written] = run(plugin, [write_call(session, report, report_content)], env)
    assert written["result"] is None
    assert report.read_text(encoding="utf-8") == report_content
    session.say("Bounded evidence retained; cross-worktree uniqueness is unknown.")
    history = json.loads(state.read_text(encoding="utf-8"))
    # Each run imports a fresh extension: stop_hook_active cannot save this test.
    for _ in range(2):
        [stopped] = run(plugin, [session.agent_end()], env)
        assert not [item for item in stopped["sent"] if item["kind"] == "user"], stopped
        assert all(item["options"].get("triggerTurn") is False for item in stopped["sent"]), stopped
        assert json.loads(state.read_text(encoding="utf-8")) == history


def test_unactivated_ordinary_stop_still_requests_required_implementation_continuation(plugin, tmp_path):
    repo = git_repo(tmp_path / "repo", {
        "src/app.py": "VALUE = 1\n", ".beads/.gitkeep": "",
    })
    session = Session(repo)
    prior_undeclared_change(session)
    session.say("I changed VALUE; next I will wire the setting in.")
    [stopped] = run(plugin, [session.agent_end()], pi_env(tmp_path))
    follow_ups = [item for item in stopped["sent"] if item["kind"] == "user"]
    assert any("no_declaration" in item["text"] for item in follow_ups), stopped
    assert all(item["options"] == {"deliverAs": "followUp"} for item in follow_ups)


@pytest.mark.parametrize("initial_phase", ["active", "report"])
def test_report_mutation_loop_is_finite_and_third_write_aborts_before_executor(plugin, inspection, tmp_path, initial_phase):
    session, env, source, report, state = inspection
    if initial_phase == "report":
        [denied] = run(plugin, [
            witness_call(session, "eval", {"code": "optional unbounded comparison"}, tmp_path / "unbounded"),
        ], env)
        assert_inspection_denied(denied, report)
    first_content = "# Findings\nInvoice provenance retained.\nComparison: unknown.\n"
    [first] = run(plugin, [write_call(session, report, first_content)], env)
    assert first["result"] is None, first
    # Count actual physical report mutations, even through a different writer.
    second_arguments = {"relative_path": str(report), "needle": "Invoice provenance retained.",
                        "repl": "Useful finding: invoice provenance retained.", "mode": "literal"}
    second_event = session.tool_call("mcp__serena_replace_content", second_arguments)
    second_event["executor"] = {"kind": "replace", "path": str(report),
                                "before": second_arguments["needle"], "after": second_arguments["repl"]}
    [second] = run(plugin, [second_event], env)
    assert second["result"] is None, second
    stable_content = "# Findings\nUseful finding: invoice provenance retained.\nComparison: unknown.\n"
    assert report.read_text(encoding="utf-8") == stable_content
    third_event = write_call(session, report, "# Findings\nUnbounded third revision.\n")
    third_event["observeAbort"] = True
    [third] = run(plugin, [third_event], env)
    assert_inspection_denied(third, report)
    assert third["aborts"] == 1, "Report-loop exhaustion must abort immediately"
    assert "executed" not in third
    assert report.read_text(encoding="utf-8") == stable_content
    assert not [item for item in third["sent"] if item["kind"] == "user"]
    record = json.loads(state.read_text(encoding="utf-8"))
    assert record["phase"] == "report"
    assert record["report_writes"][str(report.resolve())] == 2
