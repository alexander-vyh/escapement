"""Public product contract, independent of Escapement's runtime implementation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TOUR = ROOT / "docs" / "PRODUCT_TOUR.md"
EVIDENCE = ROOT / "docs" / "EVIDENCE.md"
IDENTITY = ROOT / "agent-surfaces" / "identity.json"
SUPPORT_MANIFEST = ROOT / "agent-surfaces" / "manifest.json"
CODEX_PLUGIN = ROOT / "plugins" / "escapement" / ".codex-plugin" / "plugin.json"
CLAUDE_PLUGIN = (
    ROOT / "plugins" / "escapement-claude" / ".claude-plugin" / "plugin.json"
)

CATEGORY = "The control system for agentic delivery."
PROMISE = "Delegate outcomes. Get verified delivery."
EVIDENCE_RECORDS = {
    230: {
        "observed": "An audit found that test fixtures contaminated the incident log and that a contract-verification branch was unreachable for scoped task sessions. The change isolated test state, added a leak guard with a positive control, and restored contract-gate reachability before any stricter goal policy was attempted.",
        "limit": "The planned goal requirement was not shipped. The evidence refuted that plan's premise, so this pull request repaired measurement and execution reachability first.",
    },
    234: {
        "observed": "The previous `last_run` field erased fail-then-pass history and made the apparent green rate tautological. A bounded rolling run history now preserves recent failures while the latest run continues to drive the Stop decision.",
        "limit": "Historical records still conflate “verification ran red” with “verification had not run yet.” The new history improves prospective evidence; it does not reconstruct missing past events.",
    },
    220: {
        "observed": "A public CLI check showed a second worktree reaching its own bootstrap while the first bootstrap remained blocked. Durable receipts, exact ownership, and guarded recovery preserved isolation rather than trading throughput for unsafe cleanup.",
        "limit": "The Linux/ext4 CI suite failed after merge. The macOS result and local controls were insufficient to claim a portable green delivery on their own.",
    },
    221: {
        "observed": "The follow-up made filesystem replacement controls deterministic on both macOS and Linux/ext4, then passed the focused transaction suite and CI.",
        "limit": "Production behavior was unchanged. This was a test-oracle correction required to make the earlier safety claim portable, not a second runtime feature.",
    },
    226: {
        "observed": "A captured Codex 0.153.4 `Stop` payload proved that the host emitted that lifecycle event and honored its block decision. The shipped adapter delegates decisions to the shared core, while separate fixture-shaped `UserPromptSubmit` tests prove recorder behavior without claiming a live capture of that event.",
        "limit": "Codex still has no scheduled wakeup, task-mode repository binding, or local judge rung. A session that has genuinely ended is not re-entered.",
    },
}


def _position(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position >= 0, f"public surface is missing {needle!r}"
    return position


def _record(text: str, number: int, next_number: int | None) -> str:
    start = _position(text, f"### PR #{number} ")
    if next_number is None:
        next_section = text.find("\n## ", start)
        return text[start:] if next_section < 0 else text[start:next_section]
    end = _position(text, f"### PR #{next_number} ")
    return text[start:end]


def test_readme_leads_with_category_promise_and_operator_audience():
    readme = README.read_text(encoding="utf-8")
    first_section = readme[: _position(readme, "\n## ")]

    assert CATEGORY in first_section
    assert PROMISE in first_section
    assert "operators running multiple coding-agent sessions" in first_section.lower()


def test_readme_puts_decision_material_before_install_and_deep_architecture():
    readme = README.read_text(encoding="utf-8")

    tour = _position(readme, "## The control loop in two minutes")
    evidence = _position(readme, "## Evidence, not testimonials")
    entrypoints = _position(readme, "## Start with the failure you have")
    limits = _position(readme, "## Supported hosts and truthful limits")
    install = _position(readme, "## Install current adapters")
    architecture = _position(readme, "## Architecture and operating doctrine")

    assert tour < evidence < entrypoints < limits < install < architecture
    assert "[Open the representative product tour](docs/PRODUCT_TOUR.md)" in readme
    assert "[Inspect the evidence](docs/EVIDENCE.md)" in readme


def test_representative_tour_is_labeled_and_spans_the_closed_loop():
    tour = TOUR.read_text(encoding="utf-8")

    assert "representative walkthrough" in tour.lower()
    assert "not a captured transcript" in tour.lower()
    disclosure = _position(tour.lower(), "representative walkthrough")
    first_step = _position(tour, "## 1. Delegate the outcome")
    assert disclosure < first_step
    narrative = tour[first_step:].lower()
    for contradiction in ("actual run", "verbatim transcript", "guaranteed outcome"):
        assert contradiction not in narrative
    assert "## Try it after installation" in tour
    assert "Give the agent this bounded outcome:" in tour
    assert "escapement-worktree create" in tour
    assert ".agent/runtime/test-oracle-briefs/" in tour
    assert "feature branch and pull request" in tour
    for heading in (
        "## 1. Delegate the outcome",
        "## 2. Structure the work",
        "## 3. Execute in isolation",
        "## 4. Verify independently",
        "## 5. Deliver within authority",
        "## 6. Learn from the run",
    ):
        assert heading in tour
    assert "positive control" in tour.lower()
    assert "negative control" in tour.lower()
    assert "consequential choice" in tour.lower()


def test_evidence_uses_inspectable_runs_and_preserves_counterevidence():
    evidence = EVIDENCE.read_text(encoding="utf-8")
    required_prs = (230, 234, 220, 221, 226)

    for number in required_prs:
        url = f"https://github.com/alexander-vyh/escapement/pull/{number}"
        record = _record(
            evidence,
            number,
            required_prs[required_prs.index(number) + 1]
            if number != required_prs[-1]
            else None,
        )
        nonempty_lines = [line for line in record.splitlines() if line.strip()]
        assert len(nonempty_lines) == 4, f"PR #{number} must have exactly three evidence fields"
        assert nonempty_lines[1].startswith("- **Record:** ")
        assert url in nonempty_lines[1]
        assert nonempty_lines[2] == (
            f"- **Observed outcome:** {EVIDENCE_RECORDS[number]['observed']}"
        )
        assert nonempty_lines[3] == (
            "- **Counterevidence / remaining limit:** "
            f"{EVIDENCE_RECORDS[number]['limit']}"
        )

    assert "planned goal requirement was not shipped" in _record(evidence, 230, 234).lower()
    assert "historical records still conflate" in _record(evidence, 234, 220).lower()
    assert "failed after merge" in _record(evidence, 220, 221).lower()
    assert "production behavior was unchanged" in _record(evidence, 221, 226).lower()
    assert "scheduled wakeup" in _record(evidence, 226, None).lower()
    assert "not a benchmark" in evidence.lower()


def test_relative_markdown_links_on_product_surfaces_resolve():
    markdown_link = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    for surface in (README, TOUR, EVIDENCE):
        for target in markdown_link.findall(surface.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            resolved = (surface.parent / relative).resolve()
            assert resolved.exists(), f"{surface.relative_to(ROOT)} has dead link {target}"
            if "#" in target:
                fragment = target.split("#", 1)[1]
                anchors = {
                    re.sub(
                        r"-+",
                        "-",
                        re.sub(r"[^a-z0-9 -]", "", line.lstrip("# ").lower()).replace(
                            " ", "-"
                        ),
                    ).strip("-")
                    for line in resolved.read_text(encoding="utf-8").splitlines()
                    if line.startswith("#") and " " in line
                }
                assert fragment in anchors, (
                    f"{surface.relative_to(ROOT)} has dead anchor {target}"
                )


@pytest.mark.parametrize("surface", ("docs/PRODUCT_TOUR.md", "docs/EVIDENCE.md"))
@pytest.mark.parametrize(
    "false_claim",
    (
        "Escapement guarantees that only pull requests with successful checks are merged.",
        "Repository configuration ships the release automatically.",
        "Codex re-enters completed threads until delivery finishes.",
        "Escapement is fundamentally built on Beads; Beads defines the core product.",
        "The merge gate stops unhealthy changes from reaching main.",
        "Repository settings deploy each successful merge.",
        "Codex revives finished sessions.",
        "Every configured confirmation tier pauses for approval.",
    ),
)
def test_new_product_pages_are_inside_false_support_claim_validator(
    tmp_path: Path, surface: str, false_claim: str
):
    root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", ".pytest_cache"),
    )
    path = root / surface
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Product evidence\n\n{false_claim}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(root / "tools" / "render_agent_surfaces.py"), "--check"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert surface in result.stderr


def test_plugin_listing_presents_the_full_delivery_product_not_only_test_gates():
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    codex_manifest = json.loads(CODEX_PLUGIN.read_text(encoding="utf-8"))
    plugin = codex_manifest["interface"]
    claude_manifest = json.loads(CLAUDE_PLUGIN.read_text(encoding="utf-8"))
    product = identity["product_interface"]

    assert identity["short_description"] == f"{CATEGORY} {PROMISE}"
    assert plugin["shortDescription"] == identity["short_description"]
    assert plugin["longDescription"] == (
        f"{identity['mission']} {product['long_description']}"
    )
    assert plugin["capabilities"] == identity["capabilities"]
    assert plugin["defaultPrompt"] == product["starter_prompts"]
    assert codex_manifest["keywords"] == product["keywords"]
    assert claude_manifest["description"] == (
        f"{identity['short_description']} {identity['mission']}"
    )
    assert claude_manifest["keywords"] == product["keywords"]


def test_canonical_support_manifest_describes_the_current_codex_stop_route():
    manifest = json.loads(SUPPORT_MANIFEST.read_text(encoding="utf-8"))
    hooks = {hook["id"]: hook for hook in manifest["hooks"]}
    stop_reason = hooks["stop_hook"]["hosts"]["codex"]["unsupported_reason"]
    advisory = hooks["codex_final_response_gap"]["description"]

    assert "plugin-owned" in stop_reason
    assert "user-layer ~/.codex/hooks.json" not in stop_reason
    assert "missing final-response Stop hook" not in advisory
    assert "remaining continuation gaps" in advisory


def test_renderer_consumes_canonical_product_interface(tmp_path: Path):
    root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", ".pytest_cache"),
    )
    identity_path = root / "agent-surfaces" / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["product_interface"]["starter_prompts"][0] = "SENTINEL FIRST OUTCOME"
    identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(root / "tools" / "render_agent_surfaces.py")],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    plugin = json.loads(
        (root / "plugins/escapement/.codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    assert plugin["interface"]["defaultPrompt"][0] == "SENTINEL FIRST OUTCOME"


def test_productization_adds_no_second_engine_or_service_surface():
    tracked_surface = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (README, TOUR, EVIDENCE, IDENTITY)
    ).lower()

    for forbidden in (
        "escapement lite",
        "hosted dashboard",
        "telemetry service",
        "separate engine",
    ):
        assert forbidden not in tracked_surface
