"""A landing world for shadow_verifier tests: a feature branch off a real remote
default, a fake tracker, isolated signal state.

Only process boundaries are used: a PostToolUse payload on the hook's stdin;
gate-signal lines, stdout and exit code out. The bead's oracle reports, through
a file outside the repo, the directory and commit it actually ran against.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "claude" / "hooks" / "shadow_verifier.py"
GATE = "shadow_verifier"
ACTOR = "T"  # the repo's git user.name, which bd uses as the actor by default

# The oracle: the answer must be 42 in the tree it runs in. It writes where it
# ran and at which commit to $SHADOW_TEST_MARKER -- outside the repo, because
# the runner judges a throwaway checkout of the landed commit.
CHECK = (
    "import json, os, pathlib, subprocess, app\n"
    "head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()\n"
    "pathlib.Path(os.environ['SHADOW_TEST_MARKER']).write_text(json.dumps({'cwd': os.getcwd(), 'head': head}))\n"
    "raise SystemExit(0 if app.answer() == 42 else 1)\n"
)

# Budget long enough that `bd show` and `git worktree add` on a loaded machine
# still leave the oracle time to start; the bound stays well under every
# sleeper (20-30s), so waiting on any of them still fails.
TEST_BUDGET = "8"
ELAPSED_BOUND = 16
VERDICTS = ("would-block", "would-pass", "inconclusive", "not-applicable", "not-landed", "error",
            "duplicate")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def verify_acceptance(command: str) -> str:
    return f"The answer is observable.\n\n```verify\n{command}\n```\n"


ORACLE = verify_acceptance("python3 check.py")


def _script(path: Path, body: str) -> None:
    path.write_text("#!" + sys.executable + "\n" + body)
    path.chmod(0o755)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        origin = tmp_path / "origin.git"
        self.repo = repo = tmp_path / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
        git(repo, "config", "user.email", "t@example.test")
        git(repo, "config", "user.name", ACTOR)
        (repo / "README.md").write_text("hi\n")
        (repo / "app.py").write_text("def answer():\n    return 41\n")
        (repo / "check.py").write_text(CHECK)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
        git(repo, "push", "-q", "origin", "main")
        git(repo, "remote", "set-head", "origin", "main")
        git(repo, "checkout", "-q", "-b", "feature")
        # The branch already carries a behaviour change, so every close is one a
        # verifier must judge; docs-only landings start from `fresh_branch()`.
        (repo / "lib.py").write_text("def helper():\n    return 1\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "behaviour")

        self._beads: dict[str, dict] = {}
        self._store = tmp_path / "beads.json"
        self._store.write_text("{}")
        self.shims = shims = tmp_path / "bin"
        shims.mkdir()
        _script(shims / "bd", (
            "import json, sys\n"
            f"beads = json.load(open({str(self._store)!r}))\n"
            "args = sys.argv[1:]\n"
            "if args[:1] == ['show'] and len(args) > 1 and args[1] in beads:\n"
            "    print(json.dumps([beads[args[1]]])); raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        ))
        # `gh pr view <selector> --json ...` answers from a store of PRs; any
        # other call, or an unknown selector, fails the way an unresolvable PR does.
        self._prs: dict[str, dict] = {}
        self._pr_store = tmp_path / "prs.json"
        self._pr_store.write_text("{}")
        _script(shims / "gh", (
            "import json, sys\n"
            f"prs = json.load(open({str(self._pr_store)!r}))\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['pr', 'view']:\n"
            "    rest, sel, i = args[2:], '', 0\n"
            "    while i < len(rest):\n"
            "        if rest[i] in ('--json', '-R', '--repo'): i += 2; continue\n"
            "        sel = sel or rest[i]; i += 1\n"
            "    if sel in prs: print(json.dumps(prs[sel])); raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        ))

        self.signal = signal = tmp_path / "signal"
        (signal / ".beads").mkdir(parents=True)
        self.marker = tmp_path / "oracle-ran.json"
        self.session = f"shadow-{uuid.uuid4()}"
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("CLAUDE_", "CODEX_", "ESCAPEMENT_", "BEADS_", "HARNESS_", "SHADOW_"))
        }
        env.update(
            PATH=f"{shims}:{env['PATH']}",
            BEADS_DIR=str(signal / ".beads"),
            GATE_SIGNAL_FALLBACK_DIR=str(signal),
            HARNESS_ROOT=str(tmp_path / "harness"),
            SHADOW_TEST_MARKER=str(self.marker),
            # The hook's synchronous git work: room for a loaded machine. The
            # hung-git test removes it to exercise the 2s default.
            SHADOW_VERIFIER_SYNC_SECONDS="10",
        )
        self.env = env

    def add_bead(self, bead_id: str, acceptance: str = ORACLE, assignee: str = ACTOR,
                 status: str = "closed") -> None:
        self._beads[bead_id] = {"id": bead_id, "title": "Make the answer 42", "status": status,
                                "acceptance_criteria": acceptance, "assignee": assignee}
        self._store.write_text(json.dumps(self._beads))

    def change(self, path: str, text: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", f"change {path}")

    def fresh_branch(self, name: str = "docs") -> None:
        """A branch off the remote default with no change on it yet."""
        git(self.repo, "checkout", "-q", "-b", name, "origin/main")

    def answer(self, value: int) -> None:
        self.change("app.py", f"def answer():\n    return {value}\n")

    def add_pr(self, selector: str, head: str, *, state: str = "MERGED", number: int = 12,
               files: tuple[str, ...] = ("app.py",)) -> None:
        self._prs[selector] = {"number": number, "url": f"https://github.test/o/r/pull/{number}",
                               "headRefOid": head, "state": state, "baseRefName": "main",
                               "files": [{"path": path} for path in files]}
        self._pr_store.write_text(json.dumps(self._prs))

    def dispatch(self, output: str | None = None, **agent) -> None:
        """An agent dispatch as Claude sends it (PreToolUse), and, when the
        dispatch was synchronous, its result (PostToolUse with the reply)."""
        tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
        base = {"tool_name": "Agent", "tool_input": agent, "session_id": self.session,
                "tool_use_id": tool_use_id, "cwd": str(self.repo)}
        events = [{**base, "hook_event_name": "PreToolUse"}]
        if output is not None:
            events.append({**base, "hook_event_name": "PostToolUse", "tool_response": {
                "status": "completed", "prompt": agent.get("prompt", ""),
                "content": [{"type": "text", "text": output}]}})
        for event in events:
            proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(event),
                                  capture_output=True, text=True, env=self.env, cwd=self.repo)
            assert_silent(proc)

    def challenge(self, output: str | None = None) -> None:
        self.dispatch(output, name="mutation-challenger", subagent_type="general-purpose",
                      description="Invent bad implementations", prompt="No production code.")

    def bind_session_contract(self, bead_id: str) -> None:
        thread = self.tmp / "harness" / "threads" / self.session
        thread.mkdir(parents=True, exist_ok=True)
        (thread / "contract.json").write_text(json.dumps(
            {"goal": "g", "verification_command": "python3 check.py", "source": "bead-derived",
             "thread_id": bead_id}))

    def slow_git(self, subcommand: str, seconds: int = 30) -> None:
        """Make one git subcommand hang for the hook and its runner."""
        slow = self.tmp / "slowgit"
        slow.mkdir(exist_ok=True)
        _script(slow / "git", (
            "import os, sys, time\n"
            f"if {subcommand!r} in sys.argv[1:4]: time.sleep({seconds})\n"
            f"os.execv({shutil.which('git')!r}, ['git', *sys.argv[1:]])\n"
        ))
        self.env["PATH"] = f"{slow}:{self.env['PATH']}"

    def payload(self, command: str, **overrides) -> dict:
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                   "tool_input": {"command": command},
                   "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
                   "session_id": self.session, "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
                   "cwd": str(self.repo)}
        payload.update(overrides)
        return payload

    def land(self, command: str, **overrides) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(HOOK)],
                              input=json.dumps(self.payload(command, **overrides)),
                              capture_output=True, text=True, env=self.env, cwd=self.repo,
                              timeout=120)

    def all_records(self) -> list[dict]:
        found = []
        for path in (self.signal / ".beads" / ".gate-signal.jsonl",
                     self.signal / "gate-signal-fallback.jsonl"):
            if path.is_file():
                found += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [r for r in found if r.get("gate") == GATE]

    def records(self) -> list[dict]:
        """Final records: the verdicts the promotion review counts."""
        return [r for r in self.all_records() if r["decision"] in VERDICTS]

    def provisional(self) -> list[dict]:
        return [r for r in self.all_records() if r["decision"] == "provisional"]

    def wait_final(self, count: int = 1, seconds: float = 40.0) -> list[dict]:
        """The final records, once `count` have landed (the runner is detached)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = self.records()
            if len(found) >= count:
                return found
            time.sleep(0.1)
        return self.records()

    def oracle_ran(self) -> dict | None:
        return json.loads(self.marker.read_text()) if self.marker.is_file() else None

    def worktrees(self) -> list[str]:
        return [line.split(" ", 1)[1] for line in git(self.repo, "worktree", "list", "--porcelain").splitlines()
                if line.startswith("worktree ")]


@pytest.fixture
def world(tmp_path):
    yield World(tmp_path)


def assert_silent(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", "a shadow verifier must never emit a decision"
