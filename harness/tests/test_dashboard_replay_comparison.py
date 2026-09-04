"""Frozen scope for the three Dashboard replay comparisons."""

from __future__ import annotations

import dataclasses
import json
import hashlib
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import dashboard_replay_comparison as comparison_runner  # noqa: E402
from dashboard_replay_comparison import ARM_ORDERS, REPLAYS  # noqa: E402
from measured_role_outcome import MeasuredOutcomeRun  # noqa: E402
from model_call_receipts import RoleReceipt  # noqa: E402
from pi_omp_comparison import ArmMeasurement  # noqa: E402
from verified_outcome_loop import RunResult  # noqa: E402


def test_replay_bundle_is_the_final_certified_contract_set() -> None:
    assert [(item.name, item.verifier_id, len(item.negatives)) for item in REPLAYS] == [
        ("seller_cents", "dashboards-pr722-hidden-fixtures-v2", 7),
        ("source_gaps", "dashboards-pr682-hidden-pure-state-v6", 7),
        ("launch_pacing", "dashboards-launch-pacing-no-go-v1", 2),
    ]
    assert [item.max_attempts for item in REPLAYS] == [6, 3, 3]


def test_arm_order_alternates_while_model_policy_stays_fixed() -> None:
    assert ARM_ORDERS == {
        "seller_cents": ("pi", "omp"),
        "source_gaps": ("omp", "pi"),
        "launch_pacing": ("pi", "omp"),
    }
    assert {item.provider for item in REPLAYS} == {"anthropic"}
    assert {item.model for item in REPLAYS} == {"claude-haiku-4-5"}
    assert {item.thinking for item in REPLAYS} == {"off"}
    assert {item.timeout for item in REPLAYS} == {120.0}


def _failed_arm() -> tuple[MeasuredOutcomeRun, ArmMeasurement]:
    receipt = RoleReceipt(
        role="generator",
        status="UNRESOLVED",
        candidate_generation=1,
        reason="omp_timeout",
        runtime_version="18.1.4",
        stdout_bytes=0,
        stderr_bytes=37,
        raw_events_digest="abc123",
    )
    run = MeasuredOutcomeRun(
        RunResult("UNRESOLVED", "stage_failure:RuntimeError", ()), (receipt,)
    )
    measurement = ArmMeasurement.from_receipts(
        runtime="omp",
        contract_digest="contract",
        outcome_status=run.result.status,
        receipts=run.receipts,
    )
    return run, measurement


def test_failed_arm_report_preserves_run_and_runtime_diagnostics() -> None:
    run, measurement = _failed_arm()

    value = comparison_runner._arm_json(
        run,
        measurement,
        experiment_run_id="experiment-123",
        arm_run_id="arm-456",
        replay_name="source_gaps",
        arm="omp",
    )

    assert value["run_id"] == "arm-456"
    assert value["raw_event_receipts"] == [
        {
            "experiment_run_id": "experiment-123",
            "role": "generator",
            "generation": 1,
            "status": "UNRESOLVED",
            "reason": "omp_timeout",
            "runtime_version": "18.1.4",
            "stdout_bytes": 0,
            "stderr_bytes": 37,
            "digest": "abc123",
            "bytes": 0,
            "file": "experiment-123-arm-456-source_gaps-omp-01-generator-g1.jsonl",
            "transport_stdout": (
                "experiment-123-arm-456-source_gaps-omp-generator-g1.stdout"
            ),
            "transport_stderr": (
                "experiment-123-arm-456-source_gaps-omp-generator-g1.stderr"
            ),
        }
    ]


@pytest.mark.parametrize("occupied", ["output", "event_dir", "config_root"])
def test_existing_evidence_target_fails_before_auth_or_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, occupied: str
) -> None:
    output = tmp_path / "result.json"
    event_dir = tmp_path / "events"
    config_root = tmp_path / "configs"
    targets = {"output": output, "event_dir": event_dir, "config_root": config_root}
    target = targets[occupied]
    if occupied == "output":
        target.write_text("existing evidence", encoding="utf-8")
    else:
        target.mkdir()
        (target / "sentinel").write_text("existing evidence", encoding="utf-8")

    def forbidden_auth(_: Path) -> str:
        raise AssertionError("auth must not run for an occupied evidence bundle")

    monkeypatch.setattr(comparison_runner, "_omp_token", forbidden_auth)

    with pytest.raises(FileExistsError, match=occupied):
        comparison_runner.main(
            [
                "--fixtures",
                str(tmp_path),
                "--output",
                str(output),
                "--event-dir",
                str(event_dir),
                "--config-root",
                str(config_root),
            ]
        )

    if occupied == "output":
        assert output.read_text(encoding="utf-8") == "existing evidence"
    else:
        assert (target / "sentinel").read_text(encoding="utf-8") == "existing evidence"


def test_report_publish_is_exclusive_and_leaves_no_partial_report(
    tmp_path: Path,
) -> None:
    output = tmp_path / "result.json"
    report = {"experiment_run_id": "experiment-123", "replays": {}}

    comparison_runner._publish_report_exclusively(output, report)

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".result.json.*.tmp")) == []
    with pytest.raises(FileExistsError):
        comparison_runner._publish_report_exclusively(output, {"replacement": True})
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_raw_events_are_persisted_once_under_the_experiment_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_events = '{"events":[]}'
    receipt = RoleReceipt(
        role="generator",
        status="UNRESOLVED",
        candidate_generation=1,
        reason="omp_timeout",
        runtime_version="18.1.4",
        raw_events_digest=hashlib.sha256(raw_events.encode()).hexdigest(),
        raw_events=raw_events,
    )
    run = MeasuredOutcomeRun(
        RunResult("UNRESOLVED", "stage_failure:RuntimeError", ()), (receipt,)
    )
    monkeypatch.setattr(
        comparison_runner, "run_measured_role_outcome", lambda *args, **kwargs: run
    )
    contract_arguments = {}

    def capture_contract(*args, **kwargs):
        contract_arguments.update(kwargs)
        return "contract"

    monkeypatch.setattr(comparison_runner, "contract_bundle_digest", capture_contract)
    event_dir = tmp_path / "events"
    event_dir.mkdir()

    comparison_runner._run_arm(
        arm="omp",
        frozen=SimpleNamespace(run_id="arm-456"),
        replay=REPLAYS[0],
        fixtures=tmp_path,
        event_dir=event_dir,
        token="unused",
        pi_runtime=tmp_path / "pi",
        bun_runtime=tmp_path / "bun",
        omp_adapter=tmp_path / "adapter",
        config_root=tmp_path / "configs",
        experiment_run_id="experiment-123",
        runtime_versions={"pi": "0.84.2", "omp": "omp/18.1.4", "bun": "1.4.0"},
    )

    files = list(event_dir.iterdir())
    assert [path.name for path in files] == [
        "experiment-123-arm-456-seller_cents-omp-01-generator-g1.jsonl"
    ]
    assert files[0].read_text(encoding="utf-8") == raw_events
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert contract_arguments["runtime_versions"] == (
        ("bun", "1.4.0"),
        ("omp", "omp/18.1.4"),
        ("pi", "0.84.2"),
    )
    assert contract_arguments["cwd_policy"] == "fresh-empty-role-directory"


@pytest.mark.parametrize("arm", ["pi", "omp"])
def test_arm_executes_and_records_the_same_declared_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    replay = dataclasses.replace(REPLAYS[0], timeout=37.5)
    captured: dict[str, object] = {}

    def invoke(request, **_kwargs):
        captured["request_timeout"] = request.timeout
        return RoleReceipt(
            role="generator",
            status="UNRESOLVED",
            candidate_generation=1,
            reason="controlled stop",
        )

    monkeypatch.setattr(comparison_runner, f"invoke_{arm}_role", invoke)

    def run_once(_frozen, **kwargs):
        receipt = kwargs["invoke_role"]("generator", "prompt", "system", 1)
        return MeasuredOutcomeRun(
            RunResult("UNRESOLVED", "controlled stop", ()), (receipt,)
        )

    monkeypatch.setattr(comparison_runner, "run_measured_role_outcome", run_once)

    def capture_contract(*_args, **kwargs):
        captured["contract_timeout"] = kwargs["role_timeout_seconds"]
        return "contract"

    monkeypatch.setattr(comparison_runner, "contract_bundle_digest", capture_contract)
    event_dir = tmp_path / "events"
    event_dir.mkdir()

    comparison_runner._run_arm(
        arm=arm,
        frozen=SimpleNamespace(run_id="arm-456"),
        replay=replay,
        fixtures=tmp_path,
        event_dir=event_dir,
        token="unused",
        pi_runtime=tmp_path / "pi",
        bun_runtime=tmp_path / "bun",
        omp_adapter=tmp_path / "adapter",
        config_root=tmp_path / "configs",
        experiment_run_id="experiment-123",
        runtime_versions={"pi": "0.84.2", "omp": "18.1.4", "bun": "1.4.0"},
    )

    assert captured == {"request_timeout": 37.5, "contract_timeout": 37.5}


def test_crash_survivable_manifest_is_private_and_exclusive(tmp_path: Path) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir(mode=0o700)
    manifest = comparison_runner._experiment_manifest(
        experiment_run_id="experiment-123",
        runtime_versions={"pi": "0.84.2"},
        adapter_digest="a" * 64,
        arm_run_ids={"seller_cents": {"pi": "seller-pi-run", "omp": "seller-omp-run"}},
        output=tmp_path / "result.json",
    )

    path = comparison_runner._write_manifest_exclusively(event_dir, manifest)

    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert manifest["arm_run_ids"] == {
        "seller_cents": {"pi": "seller-pi-run", "omp": "seller-omp-run"}
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        comparison_runner._write_manifest_exclusively(event_dir, manifest)


def test_main_manifest_binds_all_six_frozen_arm_run_ids_before_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = tmp_path / "adapter.ts"
    adapter.write_text("reviewed adapter", encoding="utf-8")
    run_ids = iter(f"arm-run-{index}" for index in range(6))
    captured = {}

    monkeypatch.setattr(comparison_runner, "_runtime_version", lambda _: "pinned")
    monkeypatch.setattr(
        comparison_runner,
        "_freeze",
        lambda *_: SimpleNamespace(run_id=next(run_ids)),
    )

    class ManifestCaptured(Exception):
        pass

    def capture_manifest(_event_dir, manifest):
        captured.update(manifest)
        raise ManifestCaptured

    monkeypatch.setattr(
        comparison_runner, "_write_manifest_exclusively", capture_manifest
    )
    monkeypatch.setattr(
        comparison_runner,
        "_omp_token",
        lambda _: (_ for _ in ()).throw(AssertionError("auth must follow manifest")),
    )

    with pytest.raises(ManifestCaptured):
        comparison_runner.main(
            [
                "--fixtures",
                str(tmp_path),
                "--output",
                str(tmp_path / "result.json"),
                "--event-dir",
                str(tmp_path / "events-main"),
                "--config-root",
                str(tmp_path / "configs-main"),
                "--pi-runtime",
                str(tmp_path / "pi"),
                "--omp-runtime",
                str(tmp_path / "omp"),
                "--bun-runtime",
                str(tmp_path / "bun"),
                "--omp-adapter",
                str(adapter),
            ]
        )

    arm_ids = captured["arm_run_ids"]
    assert set(arm_ids) == {"seller_cents", "source_gaps", "launch_pacing"}
    assert all(set(arms) == {"pi", "omp"} for arms in arm_ids.values())
    assert len({run_id for arms in arm_ids.values() for run_id in arms.values()}) == 6
