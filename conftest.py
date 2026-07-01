"""Pin the repo's own `_local_judge_client` for the whole test suite.

winddown_judge.py (and the deployed harness) put ``~/.claude/hooks`` first on
sys.path so the DEPLOYED harness imports the DEPLOYED client — correct in
production. In the repo's OWN test suite that is wrong: whichever test imports
winddown_judge first would cache a possibly-stale *pinned* client in
sys.modules, so contract tests that assert the client's exact request payload
(e.g. ``temperature``) pass or fail depending on collection order. That is an
order-dependent test, not a real defect.

Loading conftest happens before any test module is imported, so pinning the
repo copy here guarantees every test exercises repo code regardless of what is
installed under ``~/.claude/hooks`` or which test runs first. Production import
resolution is untouched (this file is test-only).
"""
import importlib.util
import pathlib
import sys

_repo_client = pathlib.Path(__file__).resolve().parent / "claude" / "hooks" / "_local_judge_client.py"
if _repo_client.exists():
    _spec = importlib.util.spec_from_file_location("_local_judge_client", _repo_client)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    sys.modules["_local_judge_client"] = _mod
