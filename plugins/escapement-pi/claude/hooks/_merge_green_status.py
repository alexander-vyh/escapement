"""Observe whether the pull request a merge command targets is actually green.

`.escapement/repo.json` declares `auto_merge_on_green`, and `repo_outcome.py` names its
predicate "may an agent merge a GREEN PR without asking" — but nothing ever looked at a
check. The declaration alone authorized the merge, so the word `green` in the flag was
decoration and `AGENTS.md` had to carry `merge-green-status=unsupported` as a standing
admission. This module is the missing observation.

It is a separate file from the gate on purpose: the gate owns *authority* (what the repo
declared), this owns *state* (what GitHub reports). Merging them would put two different
questions, two different failure modes, and two different external dependencies behind
one function.

Classification precedence — failing beats pending beats empty:

    failing    any check concluded FAILURE/CANCELLED/TIMED_OUT/ACTION_REQUIRED/
               STARTUP_FAILURE/ERROR
    pending    any check has not concluded yet
    no-checks  the PR exists and has no checks at all, so there is no green to observe
    green      every check concluded SUCCESS/SKIPPED/NEUTRAL, and there is at least one
    unknown    gh is missing, errored, timed out, or returned something unparseable

Only `green` and an explicit `--auto` hand-off are merge-worthy. Everything else,
including `unknown`, is not — this mirrors `repo_outcome.py`'s own philosophy that an
unresolvable check is never upgraded into an authorization.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

GH_TIMEOUT_SECONDS = 25

# Conclusions that count as a passing check. SKIPPED and NEUTRAL are included because
# GitHub's own "all checks have passed" treats them as non-blocking; excluding them would
# make every conditional job an eternal red.
_PASSING = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
_FAILING = frozenset(
    {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
)

# `gh pr merge` flags that consume the NEXT token as their value. Without this the
# parser reads `--match-head-commit <sha>` and mistakes the sha for the PR reference.
_VALUE_FLAGS = frozenset(
    {
        "-b", "--body", "-F", "--body-file", "-t", "--subject",
        "--match-head-commit", "--author-email", "-R", "--repo",
    }
)

# Shell tokens that end the `gh pr merge` invocation. shlex keeps these as whole tokens.
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", ")", "`", "}"})

_MERGE_RE = re.compile(r"gh\s+pr\s+merge\b")
_AUTO_RE = re.compile(r"(?:^|\s)--auto(?:\s|$|=)")


@dataclass(frozen=True)
class GreenStatus:
    state: str
    detail: str
    ref: Optional[str] = None

    @property
    def merge_worthy(self) -> bool:
        return self.state in {"green", "auto-delegated"}


def extract_pr_ref(command: str) -> Optional[str]:
    """The PR number, URL, or branch a `gh pr merge` command targets.

    None means "the command did not name one", which `gh` resolves from the current
    branch — so None is a legitimate answer, not a parse failure.

    Tokenized with shlex rather than str.split: `-b 'body text' 12` splits naively into
    four tokens, the skip consumes `'body`, and `text'` is then read as the PR
    reference. Checking the wrong PR's status is worse than checking none, because the
    answer looks authoritative.
    """
    match = _MERGE_RE.search(command or "")
    if not match:
        return None
    tail = command[match.end():]
    try:
        tokens = shlex.split(tail, comments=False)
    except ValueError:
        # Unbalanced quotes in an arbitrary command fragment; degrade, do not raise.
        tokens = tail.split()

    skip_next = False
    for token in tokens:
        # A separator ends this command; a `#` begins the waiver comment. Neither the
        # next command's arguments nor the waiver text may be read as a PR reference.
        if token in _SEPARATORS or token.startswith("#"):
            return None
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if "=" not in token and token in _VALUE_FLAGS:
                skip_next = True
            continue
        return token
    return None


def delegates_to_github(command: str) -> bool:
    """`gh pr merge --auto` asks GitHub to merge when its own checks go green.

    That is the safeguard this module exists to enforce, enforced by the platform rather
    than by us, so it is honored instead of duplicated.
    """
    return bool(_AUTO_RE.search(command or ""))


def _normalize(entry: dict) -> str:
    """One check entry -> 'pass' | 'fail' | 'pending'.

    Handles both rollup shapes: CheckRun (status + conclusion) and StatusContext (state).
    A CheckRun that has not COMPLETED is pending even if `conclusion` is absent, which is
    the common in-flight case and the one a naive reader mistakes for a pass.
    """
    state = (entry.get("state") or "").upper()
    if state:
        if state in _PASSING:
            return "pass"
        return "fail" if state in _FAILING else "pending"

    status = (entry.get("status") or "").upper()
    conclusion = (entry.get("conclusion") or "").upper()
    if status and status != "COMPLETED":
        return "pending"
    if not conclusion:
        return "pending"
    if conclusion in _PASSING:
        return "pass"
    return "fail" if conclusion in _FAILING else "pending"


def _name(entry: dict) -> str:
    return entry.get("name") or entry.get("context") or "check"


def classify_rollup(rollup: Sequence[dict]) -> GreenStatus:
    if not rollup:
        return GreenStatus("no-checks", "the pull request has no checks at all")

    failing, pending, recognized = [], [], 0
    for entry in rollup:
        if not isinstance(entry, dict):
            continue
        recognized += 1
        verdict = _normalize(entry)
        if verdict == "fail":
            failing.append(_name(entry))
        elif verdict == "pending":
            pending.append(_name(entry))

    if failing:
        return GreenStatus("failing", f"failing: {', '.join(sorted(set(failing)))}")
    if pending:
        return GreenStatus("pending", f"still running: {', '.join(sorted(set(pending)))}")
    if not recognized:
        # A non-empty rollup whose entries we could not read is NOT green. Falling
        # through to the green return would turn an unparseable payload into an
        # authorization, which is the one direction this module must never fail.
        return GreenStatus(
            "unknown", f"{len(rollup)} check entr(ies) in an unrecognized shape"
        )
    return GreenStatus("green", f"{recognized} check(s) passed")


def _default_runner(args: Sequence[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=cwd or None, capture_output=True, text=True,
        timeout=GH_TIMEOUT_SECONDS,
    )


def observe(
    command: str,
    cwd: str,
    runner: Optional[Callable[[Sequence[str], str], subprocess.CompletedProcess]] = None,
) -> GreenStatus:
    """Resolve the target PR's check state for a `gh pr merge` command."""
    if delegates_to_github(command):
        return GreenStatus(
            "auto-delegated",
            "--auto hands the green condition to GitHub, which merges only when its own "
            "checks pass",
        )

    ref = extract_pr_ref(command)
    run = runner or _default_runner

    if runner is None and shutil.which("gh") is None:
        return GreenStatus("unknown", "gh is not on PATH, so no check state is observable", ref)

    args = ["gh", "pr", "view"]
    if ref:
        args.append(ref)
    args += ["--json", "statusCheckRollup,state,number"]

    try:
        result = run(args, cwd)
    except subprocess.TimeoutExpired:
        return GreenStatus("unknown", f"gh pr view timed out after {GH_TIMEOUT_SECONDS}s", ref)
    except OSError as exc:
        return GreenStatus("unknown", f"could not run gh: {exc}", ref)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return GreenStatus("unknown", detail[-1][:200] if detail else "gh pr view failed", ref)

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return GreenStatus("unknown", "gh pr view returned unparseable JSON", ref)

    rollup = payload.get("statusCheckRollup")
    if rollup is None:
        return GreenStatus("unknown", "gh pr view reported no statusCheckRollup field", ref)

    status = classify_rollup(rollup)
    number = payload.get("number")
    return GreenStatus(status.state, status.detail, ref or (f"#{number}" if number else None))
