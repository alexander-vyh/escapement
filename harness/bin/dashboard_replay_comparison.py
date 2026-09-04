#!/usr/bin/env python3
"""Run the frozen Dashboard replay contracts through installed Pi and OMP."""
# file-complexity-waiver: frozen replay definitions stay beside the auditable runner

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from typing import Sequence

from measured_role_outcome import (
    ASSESSOR_PROMPT_CONTRACT,
    ASSESSOR_SYSTEM_PROMPT,
    GENERATOR_PROMPT_CONTRACT,
    GENERATOR_SYSTEM_PROMPT,
    MeasuredOutcomeRun,
    run_measured_role_outcome,
)
from omp_role_invocation import OmpRoleRequest, invoke_omp_role
from pi_omp_comparison import (
    ArmMeasurement,
    compare_arms,
    contract_bundle_digest,
)
from pi_role_invocation import PiRoleRequest, invoke_pi_role
from pi_verified_outcome_demo import _result_json
from verified_outcome_loop import FrozenSpec, Invariant, VerifierBinding


@dataclass(frozen=True)
class ReplayDefinition:
    name: str
    task: str
    invariant_id: str
    statement: str
    verifier_id: str
    verifier: str
    positive: str
    negatives: tuple[str, ...]
    max_attempts: int
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5"
    thinking: str = "off"
    timeout: float = 120.0


REPLAYS = (
    ReplayDefinition(
        name="seller_cents",
        task=(
            "Return only one SQLite SELECT query, with no markdown or commentary. "
            "The input table is seller_revenue(seller_user_id TEXT, raw_mills "
            "INTEGER), where raw_mills is thousandths of a dollar and a seller may "
            "have multiple rows. Return exactly seller_user_id and allocated_cents, "
            "one row per seller. First group each seller, round each grouped amount "
            "from mills to cents, then reconcile the seller cents so their sum equals "
            "the rounded all-seller total. If cents must be added, allocate them by "
            "largest signed rounding remainder then seller_user_id; if cents must be "
            "subtracted, allocate by smallest signed rounding remainder then "
            "seller_user_id. Support positive and negative revenue and order output "
            "by seller_user_id. Do not depend on particular seller IDs or row counts."
        ),
        invariant_id="seller-cent-reconciliation",
        statement=(
            "The query groups sellers and deterministically allocates positive or "
            "negative residual cents so seller allocated_cents sum exactly to the "
            "independently rounded total for arbitrary signed inputs and duplicate "
            "seller rows."
        ),
        verifier_id="dashboards-pr722-hidden-fixtures-v2",
        verifier="seller_cents_verifier",
        positive="seller_cents_positive.sql",
        negatives=(
            "seller_cents_naive.sql",
            "seller_cents_positive_only.sql",
            "seller_cents_hidden_id_filter.sql",
            "seller_cents_float.sql",
            "seller_cents_row_round_first.sql",
            "seller_cents_rank_one_only.sql",
            "seller_cents_nocase_tie.sql",
        ),
        max_attempts=6,
    ),
    ReplayDefinition(
        name="source_gaps",
        task=(
            "Produce a candidate whose complete content is one JavaScript ES module "
            "with no markdown or commentary inside the candidate value. Export "
            "function deriveSourceGapsState(input). Input has rows, search, "
            "previousSearch, pageIndex, and pageSize. Governed rows require a "
            "non-empty string sf_opportunity_id. Search is trimmed, case-insensitive "
            "substring matching across sf_opportunity_id, sf_account_id, "
            "sf_account_name, opportunity_name, lifecycle_status, "
            "identifier_coverage_status, remediation_owner, action_owner, "
            "remediation_reason, and remediation_next_action. Preserve governed input "
            "order. When search changes, reset the effective page index to zero; "
            "otherwise preserve it. Return exactly, in this property order: "
            "governedCount, filteredRowIds, effectivePageIndex, pageRowIds, "
            "keepTableWhenEmpty, emptyMessage. Row IDs must be sf_opportunity_id. "
            "pageRowIds is the page slice of filtered rows. keepTableWhenEmpty is true "
            "and emptyMessage is No matching source gaps. Do not depend on particular "
            "row values or counts."
        ),
        invariant_id="source-gaps-navigation-state",
        statement=(
            "The module preserves semantic opportunity identity, searches every "
            "governed remediation field case-insensitively, resets pagination on "
            "query change, paginates after filtering, excludes rows without governed "
            "IDs, and keeps the table mounted with an explicit empty message."
        ),
        verifier_id="dashboards-pr682-hidden-pure-state-v6",
        verifier="source_gaps_verifier",
        positive="source_gaps_positive.mjs",
        negatives=(
            "source_gaps_index_identity.mjs",
            "source_gaps_visible_only.mjs",
            "source_gaps_three_fields_only.mjs",
            "source_gaps_json_stringify_override.mjs",
            "source_gaps_all_values.mjs",
            "source_gaps_no_trim.mjs",
            "source_gaps_exit_poison.mjs",
        ),
        max_attempts=3,
    ),
    ReplayDefinition(
        name="launch_pacing",
        task=(
            "Obey the role system message: the full response is the single outer JSON "
            "object with a candidate string. The candidate string itself must contain "
            "a compact JSON object with exactly decision, blockers, and "
            "performance_measurement. Decide GO or NO_GO for a Launch Pacing V2 "
            "cohort from this frozen evidence: the compatibility oracle is exact "
            "fixed-snapshot semantic-key, rendered-field, filter-outcome, and "
            "global-sort parity with the legacy population. The initial serving model "
            "had 2,913 operator actions while the observed legacy page had 7,643 rows "
            "including a separate ahead-of-schedule population. A later CAKE commit "
            "added both named populations and enrichments, but no independent "
            "fixed-snapshot field/filter/sort parity comparison has reconciled that "
            "model to the legacy response. No V2 route, token, cohort, or feature flag "
            "is enabled. Latency and RSS measurement was intentionally deferred until "
            "a semantically safe candidate exists. Use blocker identifier "
            "fixed_snapshot_field_filter_sort_parity_missing when applicable. "
            "performance_measurement is RUN_NOW or DEFER_UNTIL_PARITY."
        ),
        invariant_id="dashboards-launch-pacing-safe-cohort-v1",
        statement=(
            "A cohort is GO only after exact fixed-snapshot semantic-key, "
            "rendered-field, filter-outcome, and global-sort parity; absent parity "
            "must produce NO_GO and defer performance measurement so speed cannot "
            "mask row loss."
        ),
        verifier_id="dashboards-launch-pacing-no-go-v1",
        verifier="launch_pacing_decision_verifier",
        positive="launch_pacing_no_go.json",
        negatives=(
            "launch_pacing_false_go.json",
            "launch_pacing_premature_perf.json",
        ),
        max_attempts=3,
    ),
)

ARM_ORDERS = {
    "seller_cents": ("pi", "omp"),
    "source_gaps": ("omp", "pi"),
    "launch_pacing": ("pi", "omp"),
}


def _freeze(fixtures: pathlib.Path, replay: ReplayDefinition) -> FrozenSpec:
    binding = VerifierBinding.freeze(
        verifier_id=replay.verifier_id,
        executable=(fixtures / replay.verifier).resolve(),
    )
    invariant = Invariant.freeze(
        identifier=replay.invariant_id,
        statement=replay.statement,
        verifier=binding,
        positive_control=(fixtures / replay.positive).read_bytes(),
        negative_controls=tuple(
            (fixtures / name).read_bytes() for name in replay.negatives
        ),
    )
    return FrozenSpec.freeze((invariant,))


def _omp_token(omp_runtime: pathlib.Path) -> str:
    completed = subprocess.run(
        (str(omp_runtime), "token", "anthropic"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token or "\n" in token or len(token) > 64_000:
        raise RuntimeError("OMP did not provide one bounded Anthropic bearer")
    return token


def _run_arm(
    *,
    arm: str,
    frozen: FrozenSpec,
    replay: ReplayDefinition,
    fixtures: pathlib.Path,
    event_dir: pathlib.Path,
    token: str,
    pi_runtime: pathlib.Path,
    bun_runtime: pathlib.Path,
    omp_adapter: pathlib.Path,
    config_root: pathlib.Path,
    experiment_run_id: str,
    runtime_versions: dict[str, str],
) -> tuple[MeasuredOutcomeRun, ArmMeasurement]:
    def invoke(role: str, prompt: str, system_prompt: str, generation: int):
        evidence_prefix = event_dir / _transport_prefix(
            experiment_run_id,
            frozen.run_id,
            replay.name,
            arm,
            role,
            generation,
        )
        if arm == "pi":
            return invoke_pi_role(
                PiRoleRequest(
                    role=role,
                    prompt=prompt,
                    provider=replay.provider,
                    model=replay.model,
                    system_prompt=system_prompt,
                    thinking=replay.thinking,
                    timeout=replay.timeout,
                    candidate_generation=generation,
                ),
                pi_runtime=pi_runtime,
                config_root=config_root / replay.name / arm,
                cwd=fixtures,
                auth_env={"ANTHROPIC_AUTH_TOKEN": token},
                evidence_prefix=evidence_prefix,
            )
        return invoke_omp_role(
            OmpRoleRequest(
                role=role,
                prompt=prompt,
                provider=replay.provider,
                model=replay.model,
                auth_token=token,
                system_prompt=system_prompt,
                timeout=replay.timeout,
                candidate_generation=generation,
            ),
            bun_runtime=bun_runtime,
            adapter=omp_adapter,
            config_root=config_root / replay.name / arm,
            evidence_prefix=evidence_prefix,
        )

    run = run_measured_role_outcome(
        frozen,
        task=replay.task,
        max_attempts=replay.max_attempts,
        max_input_bytes=1_048_576,
        invoke_role=invoke,
    )
    for index, receipt in enumerate(run.receipts, 1):
        if not receipt.raw_events_digest:
            if receipt.raw_events:
                raise RuntimeError("raw events exist without a digest")
            continue
        extension = "jsonl"
        path = event_dir / _raw_event_filename(
            experiment_run_id,
            frozen.run_id,
            replay.name,
            arm,
            index,
            receipt,
            extension=extension,
        )
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(receipt.raw_events)
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.raw_events_digest:
            raise RuntimeError("persisted raw event digest mismatch")
    contract_digest = contract_bundle_digest(
        frozen,
        task=replay.task,
        provider=replay.provider,
        model=replay.model,
        max_attempts=replay.max_attempts,
        generator_system_prompt=GENERATOR_SYSTEM_PROMPT,
        assessor_system_prompt=ASSESSOR_SYSTEM_PROMPT,
        generator_prompt_template=GENERATOR_PROMPT_CONTRACT,
        assessor_prompt_template=ASSESSOR_PROMPT_CONTRACT,
        cwd_policy=(
            "fixture-directory" if arm == "pi" else "fresh-empty-role-directory"
        ),
        thinking=replay.thinking,
        role_timeout_seconds=replay.timeout,
        max_input_bytes=1_048_576,
        runtime_versions=tuple(sorted(runtime_versions.items())),
        package_versions=(("omp_dependency", "18.1.4"),),
    )
    measurement = ArmMeasurement.from_receipts(
        runtime=arm,
        contract_digest=contract_digest,
        outcome_status=run.result.status,
        receipts=run.receipts,
    )
    return run, measurement


def _measurement_json(measurement: ArmMeasurement) -> dict[str, object]:
    fields = (
        "runtime",
        "contract_digest",
        "outcome_status",
        "model_call_count",
        "measurement_status",
        "topology_status",
        "identity_status",
        "total_input_tokens",
        "total_output_tokens",
        "total_cache_read_tokens",
        "total_cache_write_tokens",
        "total_tokens",
        "total_cost_usd",
        "total_duration_ms",
        "evidence_digest",
    )
    return {field: getattr(measurement, field) for field in fields}


def _raw_event_filename(
    experiment_run_id: str,
    arm_run_id: str,
    replay_name: str,
    arm: str,
    index: int,
    receipt: object,
    *,
    extension: str,
) -> str:
    role = getattr(receipt, "role")
    generation = getattr(receipt, "candidate_generation")
    return (
        f"{experiment_run_id}-{arm_run_id}-{replay_name}-{arm}-{index:02d}-{role}-"
        f"g{generation}.{extension}"
    )


def _transport_prefix(
    experiment_run_id: str,
    arm_run_id: str,
    replay_name: str,
    arm: str,
    role: str,
    generation: int,
) -> str:
    return f"{experiment_run_id}-{arm_run_id}-{replay_name}-{arm}-{role}-g{generation}"


def _arm_json(
    run: MeasuredOutcomeRun,
    measurement: ArmMeasurement,
    *,
    experiment_run_id: str,
    arm_run_id: str,
    replay_name: str,
    arm: str,
) -> dict[str, object]:
    return {
        "run_id": arm_run_id,
        "outcome": _result_json(run.result),
        "measurement": _measurement_json(measurement),
        "calls": [
            dataclasses.asdict(call)
            for receipt in run.receipts
            for call in receipt.model_calls
        ],
        "raw_event_receipts": [
            {
                "experiment_run_id": experiment_run_id,
                "role": receipt.role,
                "generation": receipt.candidate_generation,
                "status": receipt.status,
                "reason": receipt.reason,
                "runtime_version": receipt.runtime_version,
                "stdout_bytes": receipt.stdout_bytes,
                "stderr_bytes": receipt.stderr_bytes,
                "digest": receipt.raw_events_digest,
                "bytes": len(receipt.raw_events.encode("utf-8")),
                "file": (
                    _raw_event_filename(
                        experiment_run_id,
                        arm_run_id,
                        replay_name,
                        arm,
                        index,
                        receipt,
                        extension="jsonl",
                    )
                    if receipt.raw_events_digest
                    else None
                ),
                "transport_stdout": (
                    _transport_prefix(
                        experiment_run_id,
                        arm_run_id,
                        replay_name,
                        arm,
                        receipt.role,
                        receipt.candidate_generation,
                    )
                    + ".stdout"
                ),
                "transport_stderr": (
                    _transport_prefix(
                        experiment_run_id,
                        arm_run_id,
                        replay_name,
                        arm,
                        receipt.role,
                        receipt.candidate_generation,
                    )
                    + ".stderr"
                ),
            }
            for index, receipt in enumerate(run.receipts, 1)
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--event-dir", type=pathlib.Path, required=True)
    parser.add_argument("--config-root", type=pathlib.Path, required=True)
    parser.add_argument(
        "--pi-runtime", type=pathlib.Path, default="/opt/homebrew/bin/pi"
    )
    parser.add_argument(
        "--omp-runtime", type=pathlib.Path, default="node_modules/.bin/omp"
    )
    parser.add_argument(
        "--bun-runtime",
        type=pathlib.Path,
        default=pathlib.Path(shutil.which("bun") or "bun"),
    )
    parser.add_argument(
        "--omp-adapter",
        type=pathlib.Path,
        default=pathlib.Path(__file__).with_name("omp_role_adapter.ts"),
    )
    return parser


def _claim_evidence_targets(output, event_dir, config_root) -> None:
    targets = (
        ("output", output),
        ("event_dir", event_dir),
        ("config_root", config_root),
    )
    for label, path in targets:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"{label} already exists: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=False)
    config_root.mkdir(parents=True, exist_ok=False)
    event_dir.chmod(0o700)
    config_root.chmod(0o700)


def _runtime_version(command: tuple[str, ...]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value or "\n" in value or len(value) > 1024:
        raise RuntimeError(f"runtime identity unavailable: {command[0]}")
    return value


def _publish_report_exclusively(
    output: pathlib.Path, report: dict[str, object]
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid.uuid4()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            temporary.chmod(0o600)
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest_exclusively(
    event_dir: pathlib.Path, manifest: dict[str, object]
) -> pathlib.Path:
    path = event_dir / "experiment-manifest.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _experiment_manifest(
    *,
    experiment_run_id: str,
    runtime_versions: dict[str, str],
    adapter_digest: str,
    arm_run_ids: dict[str, dict[str, str]],
    output: pathlib.Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "experiment_run_id": experiment_run_id,
        "runtime_versions": runtime_versions,
        "omp_adapter_digest": adapter_digest,
        "arm_run_ids": arm_run_ids,
        "output": str(output.resolve()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _claim_evidence_targets(args.output, args.event_dir, args.config_root)
    experiment_run_id = str(uuid.uuid4())
    runtime_versions = {
        "pi": _runtime_version((str(args.pi_runtime.resolve()), "--version")),
        "omp": _runtime_version((str(args.omp_runtime.resolve()), "--version")),
        "bun": _runtime_version((str(args.bun_runtime.resolve()), "--version")),
    }
    adapter_digest = hashlib.sha256(args.omp_adapter.read_bytes()).hexdigest()
    frozen_specs: dict[tuple[str, str], FrozenSpec] = {}
    arm_run_ids: dict[str, dict[str, str]] = {}
    for replay in REPLAYS:
        arm_run_ids[replay.name] = {}
        for arm in ARM_ORDERS[replay.name]:
            frozen = _freeze(args.fixtures, replay)
            frozen_specs[(replay.name, arm)] = frozen
            arm_run_ids[replay.name][arm] = frozen.run_id
    _write_manifest_exclusively(
        args.event_dir,
        _experiment_manifest(
            experiment_run_id=experiment_run_id,
            runtime_versions=runtime_versions,
            adapter_digest=adapter_digest,
            arm_run_ids=arm_run_ids,
            output=args.output,
        ),
    )
    token = _omp_token(args.omp_runtime.resolve())
    report: dict[str, object] = {
        "schema_version": 2,
        "experiment_run_id": experiment_run_id,
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "thinking": "off",
        "runtime_versions": runtime_versions,
        "omp_adapter_digest": adapter_digest,
        "replays": {},
    }
    replay_results = report["replays"]
    assert isinstance(replay_results, dict)
    for replay in REPLAYS:
        arms: dict[str, object] = {}
        measurements: dict[str, ArmMeasurement] = {}
        for arm in ARM_ORDERS[replay.name]:
            print(f"running {replay.name} via {arm}", file=sys.stderr, flush=True)
            frozen = frozen_specs[(replay.name, arm)]
            run, measurement = _run_arm(
                arm=arm,
                frozen=frozen,
                replay=replay,
                fixtures=args.fixtures,
                event_dir=args.event_dir,
                token=token,
                pi_runtime=args.pi_runtime,
                bun_runtime=args.bun_runtime,
                omp_adapter=args.omp_adapter,
                config_root=args.config_root,
                experiment_run_id=experiment_run_id,
                runtime_versions=runtime_versions,
            )
            arms[arm] = _arm_json(
                run,
                measurement,
                experiment_run_id=experiment_run_id,
                arm_run_id=frozen.run_id,
                replay_name=replay.name,
                arm=arm,
            )
            measurements[arm] = measurement
            print(
                f"finished {replay.name} via {arm}: "
                f"{run.result.status}, {measurement.model_call_count} calls",
                file=sys.stderr,
                flush=True,
            )
        replay_results[replay.name] = {
            "arm_order": list(ARM_ORDERS[replay.name]),
            "max_attempts": replay.max_attempts,
            "arms": arms,
            "comparison": dataclasses.asdict(
                compare_arms(measurements["pi"], measurements["omp"])
            ),
        }
    _publish_report_exclusively(args.output, report)
    print(json.dumps(report, sort_keys=True))
    comparisons = [
        value["comparison"]["status"]
        for value in replay_results.values()
        if isinstance(value, dict)
    ]
    return 0 if comparisons and all(item == "COMPARABLE" for item in comparisons) else 2


if __name__ == "__main__":
    raise SystemExit(main())
