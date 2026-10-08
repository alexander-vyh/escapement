"""Drive the rendered Pi extension with submitted prompts: every prompt's
system prompt carries the true current local time, in the zone Pi runs in.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

LINE = re.compile(r"now: \w{3} (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) (\S+) \(UTC([+-]\d{4})\)")


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _ist(moment: datetime) -> datetime:
    """Wall-clock time in Kolkata (+0530, no DST), computed from the instant."""
    return datetime.fromtimestamp(moment.timestamp(), tz=timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)


def _time_in(prompt: str):
    found = LINE.findall(prompt)
    assert len(found) == 1, prompt
    return found[0]


def test_pi_every_prompt_carries_the_local_time(plugin, tmp_path):
    repo = git_repo(tmp_path / "project", {"README.md": "demo\n"})
    env = {**pi_env(tmp_path), "TZ": "Asia/Kolkata"}
    session = Session(repo)

    before = datetime.now().astimezone()
    first, second = run(plugin, [session.prompt("one"), session.prompt("two")], env)
    after = datetime.now().astimezone()

    for outcome in (first, second):
        prompt = outcome["result"]["systemPrompt"]
        assert prompt.startswith("BASE PROMPT")
        date, hm, abbr, offset = _time_in(prompt)
        # Kolkata is +0530 year-round; abbreviation is the TZ database's.
        assert offset == "+0530" and abbr == "IST"
        local = datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M")
        assert _ist(before) - timedelta(seconds=90) <= local <= _ist(after) + timedelta(seconds=90)
