"""Public gate oracle: parents dispatch; identified workers return findings.

Codex identity comes from the recorded native subagent payload. Pi identity
comes from its parentSession header projected onto parent_session. Claude's
existing child environment seam is exercised, not claimed as a live-host replay.
Unknown/missing host identity remains unproven; prompts never establish authority.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / 'claude/hooks/enforce_named_agents.py'
RECORDED = json.loads((Path(__file__).parent / 'fixtures/codex_agent_mcp_stop_payloads.json').read_text())['payloads']


def invoke(tmp_path, host, tool, arguments, identity=None, child_env=False):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_', 'CODEX_', 'ESCAPEMENT_', 'BEADS_'))}
    env.update(HOME=str(tmp_path), ESCAPEMENT_HOST=host,
               GATE_SIGNAL_FALLBACK_DIR=str(tmp_path / 'signals'))
    if child_env:
        env['CLAUDE_AGENT_ID'] = 'assigned-worker'
    payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool,
               'tool_input': arguments, 'session_id': 'scope-fixture', 'cwd': str(tmp_path)}
    payload.update(identity or {})
    result = subprocess.run([sys.executable, '-B', str(HOOK)], input=json.dumps(payload),
                            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


@pytest.mark.parametrize('host,tool,args,identity,child_env', [
    ('claude', 'Agent', {'name': 'moreprep', 'prompt': 'Prepare another preparation plan.'}, {}, True),
    ('codex', RECORDED['spawn_agent_pretooluse']['tool_name'],
     RECORDED['spawn_agent_pretooluse']['tool_input'],
     {'agent_id': RECORDED['subagent_bash_pretooluse']['agent_id']}, False),
    ('pi', 'Agent', {'name': 'scout', 'prompt': 'Prepare another preparation plan.'},
     {'parent_session': '/sessions/parent.jsonl'}, False),
])
def test_identified_worker_cannot_spawn_more_preparation(tmp_path, host, tool, args, identity, child_env):
    # A naming waiver must not grant permission to recursively delegate.
    args = {**args, 'enforce_named_agents_waiver': 'My assignment would be easier with another child.'}
    out = invoke(tmp_path, host, tool, args, identity, child_env)
    hook = out['hookSpecificOutput']
    assert hook['permissionDecision'] == 'deny'
    reason = hook['permissionDecisionReason'].lower()
    assert 'supervisor' in reason and 'inline' in reason
    signals = tmp_path / 'signals'
    assert any('delegated_worker_dispatch' in path.read_text()
               for path in signals.rglob('*.jsonl'))


@pytest.mark.parametrize('host,tool,args', [
    ('claude', 'Agent', {'name': 'qa', 'prompt': 'Run scoped QA.'}),
    ('codex', RECORDED['spawn_agent_pretooluse']['tool_name'], RECORDED['spawn_agent_pretooluse']['tool_input']),
    ('pi', 'Agent', {'name': 'scout', 'prompt': 'Inspect assigned files.'}),
])
def test_standalone_parent_keeps_regular_named_dispatch(tmp_path, host, tool, args):
    assert invoke(tmp_path, host, tool, args) is None


@pytest.mark.parametrize('tool,args', [
    ('Bash', {'command': 'pytest tests/assigned -q'}),
    ('Edit', {'file_path': 'assigned.py', 'old_string': 'old', 'new_string': 'new'}),
])
@pytest.mark.parametrize('host,identity,child_env', [
    ('claude', {}, True),
    ('codex', {'agent_id': RECORDED['subagent_bash_pretooluse']['agent_id']}, False),
    ('pi', {'parent_session': '/sessions/parent.jsonl'}, False),
])
def test_worker_inline_edits_and_tests_are_not_dispatch(tmp_path, tool, args, host, identity, child_env):
    assert invoke(tmp_path, host, tool, args, identity, child_env) is None


def test_anonymous_worker_cannot_use_naming_waiver_as_delegation_authority(tmp_path):
    out = invoke(tmp_path, 'claude', 'Agent',
                 {'enforce_named_agents_waiver': 'This child must be anonymous for an isolated probe.'},
                 child_env=True)
    assert out['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert 'supervisor' in out['hookSpecificOutput']['permissionDecisionReason']


def test_tool_arguments_cannot_claim_child_identity_or_delegation_permission(tmp_path):
    assert invoke(tmp_path, 'claude', 'Agent',
                  {'name': 'qa', 'parent_session': 'invented', 'can_delegate': True}) is None
    out = invoke(tmp_path, 'pi', 'Agent', {'name': 'qa', 'can_delegate': True},
                 {'parent_session': '/sessions/parent.jsonl'})
    assert out['hookSpecificOutput']['permissionDecision'] == 'deny'
