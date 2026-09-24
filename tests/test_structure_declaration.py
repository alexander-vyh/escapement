"""Tests for declared structural intent, coverage honesty, and bootstrap.

Each test here defends a failure that actually happened in this estate, not a
property that seemed nice to have.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import structure_adapters as adapters  # noqa: E402
import structure_bootstrap as bootstrap  # noqa: E402
import structure_declaration as decl  # noqa: E402


def _pin(**over):
    base = {"path": "a/b.py", "target": {"complexity": 40}, "owner": "alex",
            "created": "2026-09-01"}
    base.update(over)
    return base


def _waiver(**over):
    base = {"path": "a/b.py", "reason": "generated from the vendor schema; "
                                        "splitting it would desync on regeneration",
            "owner": "alex", "expires": "2026-12-01"}
    base.update(over)
    return base


# --- the pin/waiver distinction -------------------------------------------


def test_pin_without_a_target_is_not_a_pin():
    """A pin is an obligation. With no target it obliges nothing and reads as done."""
    d = decl.parse({"pins": [_pin(target=None)]})
    assert not d.valid
    assert any("target" in p for p in d.problems)
    assert not d.pins, "a pin missing its obligation was still accepted"


def test_waiver_without_an_expiry_is_not_a_waiver():
    """An unexpiring waiver is a permanent policy change made without review."""
    d = decl.parse({"waivers": [_waiver(expires=None)]})
    assert not d.valid
    assert any("expires" in p for p in d.problems)
    assert not d.waivers


def test_a_record_cannot_be_both_a_pin_and_a_waiver():
    """The conflation this schema exists to prevent.

    Growth in a waiver surface tracked degrading outcomes here; growth in a pin
    surface tracked improving ones. A record that is both makes the combined
    count's sign meaningless, so it is rejected rather than coerced.
    """
    hybrid = _pin()
    hybrid["expires"] = "2026-12-01"
    hybrid["reason"] = "we will get to it"
    d = decl.parse({"pins": [hybrid]})
    assert not d.valid
    assert any("other record type" in p for p in d.problems)


def test_pin_and_waiver_are_reported_separately():
    """Never one 'declarations' number: the two predict opposite futures."""
    text = decl.render(decl.parse({"pins": [_pin()], "waivers": [_waiver(path="c/d.py")]}))
    assert "pins        1" in text and "waivers     1" in text
    assert "declarations" not in text.lower()


def test_expired_waiver_is_named():
    d = decl.parse({"waivers": [_waiver(expires="2026-01-01")]})
    assert decl.expired(d, "2026-09-24"), "an expired waiver was still treated as live"
    assert "EXPIRED" in decl.render(d, "2026-09-24")


# --- the echo rule, and its agreement with the shipped gate ----------------


def test_waiver_reason_that_restates_the_path_is_rejected():
    """1,419 of 1,419 waiver reasons in this repo were a filesystem path.

    Every presence check passed while the corpus contained no argument at all.
    """
    d = decl.parse({"waivers": [_waiver(reason="a/b.py")]})
    assert not d.valid
    assert any("not an argument" in p for p in d.problems)


def test_exclusion_must_forecast_not_restate():
    d = decl.parse({"exclusions": [{"path": "src/vendor", "why": "src/vendor"}]})
    assert not d.valid
    assert any("forecast" in p for p in d.problems)


def test_echo_rule_agrees_with_the_gate():
    """Two implementations of one invariant, pinned to each other.

    The file-complexity gate ships in four standalone copies and cannot import
    this module, so the rule is deliberately written twice. This test is what
    stops the duplicate from becoming a divergence nobody notices — the exact
    failure mode that let a gate pass 1,419 times while checking nothing.
    """
    spec = importlib.util.spec_from_file_location(
        "_fcg", ROOT / "claude" / "hooks" / "file_complexity_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    corpus = [
        ("src/app/models.py", "src/app/models.py"),
        ("src/app/models.py", "models.py"),
        ("src/app/models.py", ""),
        ("src/app/models.py", "   "),
        ("src/app/models.py", "src/other/thing.py"),
        ("src/app/models.py", "generated from the vendor schema; splitting it "
                              "desyncs on regeneration"),
        ("src/app/models.py", "one big state machine, and splitting the arms "
                              "hides the transition table"),
        ("src/app/models.py", "see src/app/models.py for why"),
    ]
    for path, reason in corpus:
        assert decl.is_artifact_echo(reason, path) == gate._is_artifact_echo(reason, path), (
            f"echo rule diverged from the shipped gate on {reason!r}"
        )


# --- coverage: unmeasured is not the same as clean -------------------------


def test_unavailable_adapter_measures_nothing_and_says_so():
    """`dashboards` read as structurally clean for four months.

    1,242 JavaScript files were never measured, and silence was indistinguishable
    from health. An unavailable adapter must be visible in the output.
    """
    missing = adapters.Adapter("javascript", "lizard", "lizard not installed")
    assert not missing.available
    assert missing.why_unavailable, "an unavailable adapter carried no reason"


def test_measure_returns_nothing_rather_than_zero_for_an_unknown_language():
    assert adapters.measure("/nonexistent", ["a.txt"], "cobol") == {}


def test_coverage_counts_scope_and_adapter_failures_alike(tmp_path):
    """Either failure alone produces the same silence, so both must count."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "other").mkdir()
    for name in ("src/a.py", "src/b.py", "other/c.py"):
        (tmp_path / name).write_text("x = 1\n")
    (tmp_path / "src" / "app.sh").write_text("echo hi\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    cov = adapters.coverage(str(tmp_path), ["src"])
    assert cov.by_language["python"]["measured"] == 2, "in-scope python not measured"
    assert cov.by_language["python"]["files"] == 3, "out-of-scope file left out of denominator"
    # Shell is in scope but has no adapter: in scope, still unmeasured.
    assert cov.by_language["shell"]["in_scope"] == 1
    assert cov.by_language["shell"]["measured"] == 0
    assert cov.total == 4 and cov.measured == 2
    assert 0.49 < cov.fraction < 0.51


def test_coverage_report_names_every_unmeasured_language(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "x.sh").write_text("echo\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    text = adapters.render(adapters.coverage(str(tmp_path), ["x.sh"]))
    assert "shell" in text
    assert "Unmeasured code is not healthy code" in text


def _js_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    return tmp_path


def test_file_with_no_functions_measures_zero_rather_than_vanishing(tmp_path):
    """140 of dashboards' 683 JavaScript files declare no function at all.

    They are constants, re-exports and config. Treating "the analyser returned
    no rows" as "the analyser failed" would have reported 141 files unmeasured
    when exactly one was.
    """
    if not adapters._have("lizard"):
        return
    repo = _js_repo(tmp_path)
    (repo / "src" / "consts.js").write_text("export const LIMIT = 5;\n")
    (repo / "src" / "work.js").write_text(
        "export function f(a) { if (a) { return 1; } return 2; }\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    got = adapters.measure(str(repo), ["src/consts.js", "src/work.js"], "javascript")
    assert got.get("src/consts.js") == 0.0, "a function-free file was reported as unmeasured"
    assert got.get("src/work.js", 0) >= 2, "a branching function measured no complexity"


def test_file_the_analyser_cannot_finish_stays_absent(monkeypatch, tmp_path):
    """One 563-line .mjs in this estate hangs lizard forever.

    An unfinishable file must not land in the results as a confident 0.0, which
    is indistinguishable from simple code.
    """
    repo = _js_repo(tmp_path)
    (repo / "src" / "evil.js").write_text("// hangs\n")
    monkeypatch.setattr(adapters, "_have", lambda _b: True)
    monkeypatch.setattr(adapters, "_run_lizard", lambda *a, **k: None)

    assert adapters.measure(str(repo), ["src/evil.js"], "javascript") == {}


def test_measurement_never_walks_untracked_vendor_trees(tmp_path):
    """Pointing the analyser at a directory walked 377 vendored packages.

    It wedged the whole run and would have counted third-party code as this
    repository's complexity. Only tracked files are ever handed over.
    """
    if not adapters._have("lizard"):
        return
    repo = _js_repo(tmp_path)
    (repo / "src" / "app.js").write_text("export function a() { return 1; }\n")
    vendor = repo / "src" / "node_modules" / "left-pad"
    vendor.mkdir(parents=True)
    (vendor / "index.js").write_text(
        "function v(x){" + "if(x){}" * 50 + "return x;}\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/app.js"], check=True)

    got = adapters.measure(str(repo), ["src/app.js"], "javascript")
    assert set(got) == {"src/app.js"}, f"vendored code leaked into the measurement: {got}"


def test_vendored_trees_stay_out_of_the_denominator():
    """Coverage must not be diluted by code this repository does not own."""
    assert any(seg in "node_modules/react/index.js" for seg in adapters.IGNORED_SEGMENTS)
    assert not any(seg in "src/domains/sales/Tab.jsx" for seg in adapters.IGNORED_SEGMENTS)


# --- bootstrap -------------------------------------------------------------


def test_bootstrap_skeleton_does_not_validate_until_reviewed(tmp_path):
    """A generated forecast is worthless, so the skeleton is born invalid.

    An exclusion says the next defect will not be here. Nothing can generate
    that claim, and an unexamined skeleton must not be mistakable for a
    considered one.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.sh").write_text("echo\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    scope = bootstrap.candidate_scope(str(tmp_path))
    assert scope == ["src"]
    data = bootstrap.skeleton(str(tmp_path), scope)
    assert not decl.parse(data).valid, "a generated skeleton validated without review"


def test_bootstrap_writes_a_loadable_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    path = bootstrap.write(str(tmp_path), bootstrap.skeleton(str(tmp_path), ["src"]))
    assert path.exists()
    assert json.loads(path.read_text())["scope"] == ["src"]
    assert decl.load(str(tmp_path)) is not None


def test_missing_declaration_is_absent_not_empty():
    """An absent declaration and an empty one mean different things."""
    assert decl.load("/nonexistent/repo") is None


def test_malformed_declaration_reports_rather_than_raises(tmp_path):
    (tmp_path / ".escapement").mkdir()
    (tmp_path / ".escapement" / "structure.json").write_text("{not json")
    d = decl.load(str(tmp_path))
    assert d is not None and not d.valid
    assert any("invalid JSON" in p for p in d.problems)


def test_every_problem_is_reported_not_just_the_first():
    """A validator that stops at the first error turns review into a slow loop."""
    d = decl.parse({
        "pins": [_pin(target=None), _pin(owner=None)],
        "waivers": [_waiver(expires=None)],
    })
    assert len(d.problems) >= 3, f"expected every problem, got {d.problems}"


# --- dbt: the one stored artifact we consume ------------------------------


import structure_dbt as dbt  # noqa: E402


def _dbt_repo(tmp_path, generated="2026-09-01T00:00:00Z"):
    (tmp_path / "dbt" / "models").mkdir(parents=True)
    (tmp_path / "dbt" / "target").mkdir(parents=True)
    (tmp_path / "dbt" / "models" / "a.sql").write_text("select 1\n")
    (tmp_path / "dbt" / "models" / "b.sql").write_text("select * from {{ ref('a') }}\n")
    manifest = {
        "metadata": {"generated_at": generated, "dbt_version": "1.10.16"},
        "nodes": {
            "model.p.a": {"resource_type": "model",
                          "original_file_path": "models/a.sql",
                          "depends_on": {"nodes": []}},
            "model.p.b": {"resource_type": "model",
                          "original_file_path": "models/b.sql",
                          "depends_on": {"nodes": ["model.p.a", "source.p.raw"]}},
            "test.p.t": {"resource_type": "test",
                         "original_file_path": "tests/t.sql",
                         "depends_on": {"nodes": ["model.p.a"]}},
        },
    }
    (tmp_path / "dbt" / "target" / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_manifest_paths_are_rebased_onto_the_repository_root(tmp_path):
    """dbt records paths relative to its project dir, git does not.

    A graph whose keys never match `git ls-files` matches nothing and reports as
    an empty result rather than as an error — silence again, from a mismatch of
    two path conventions.
    """
    m = dbt.load(str(_dbt_repo(tmp_path)))
    assert set(m.models) == {"dbt/models/a.sql", "dbt/models/b.sql"}
    assert m.models["dbt/models/b.sql"] == ["dbt/models/a.sql"]


def test_edges_leaving_the_model_set_are_counted_not_dropped(tmp_path):
    """A sparse-looking graph and a graph with external edges differ."""
    m = dbt.load(str(_dbt_repo(tmp_path)))
    assert m.unresolved == 1, "a source edge was silently discarded"


def test_a_manifest_older_than_its_models_is_reported_stale(tmp_path):
    """The compromise that makes consuming a stored artifact acceptable.

    A three-month-old complexity baseline went on being quoted as current in
    this estate. An artifact that cannot announce its own staleness repeats it.
    """
    repo = _dbt_repo(tmp_path)
    manifest_path = repo / "dbt" / "target" / "manifest.json"
    os.utime(manifest_path, (1_600_000_000, 1_600_000_000))
    m = dbt.load(str(repo))
    assert m.stale, "a model edited after the manifest was not reported"
    assert not m.fresh
    assert "STALE" in dbt.render(m)


def test_a_current_manifest_is_not_cried_wolf_over(tmp_path):
    """A staleness check that always fires is ignored within a week."""
    repo = _dbt_repo(tmp_path)
    future = 2_000_000_000
    os.utime(repo / "dbt" / "target" / "manifest.json", (future, future))
    m = dbt.load(str(repo))
    assert m.fresh and "STALE" not in dbt.render(m)


def test_coverage_counts_dbt_tests_not_only_models(tmp_path):
    """cake tracks 547 models and 681 data tests.

    Counting only models would report first-party SQL that dbt fully resolves
    as unmeasured, understating coverage by more than the models themselves.
    """
    described = dbt.described_files(str(_dbt_repo(tmp_path)))
    assert "dbt/tests/t.sql" in described
    assert "dbt/models/a.sql" in described


def test_sql_adapter_needs_a_manifest_not_the_dbt_binary(tmp_path):
    """Requiring the executable leaves half of `cake` permanently unmeasured."""
    without = adapters.adapters(str(tmp_path))["sql"]
    assert not without.available and "dbt parse" in without.why_unavailable
    assert adapters.adapters(str(_dbt_repo(tmp_path)))["sql"].available


def test_missing_manifest_is_absent_not_empty():
    assert dbt.load("/nonexistent/repo") is None
    assert dbt.described_files("/nonexistent/repo") == set()


def test_corrupt_manifest_does_not_raise(tmp_path):
    (tmp_path / "target").mkdir(parents=True)
    (tmp_path / "target" / "manifest.json").write_text("{truncated")
    assert dbt.load(str(tmp_path)) is None


def test_vendored_dbt_packages_stay_out_of_the_denominator():
    """575 of cake's 1,952 SQL files are third-party dbt packages."""
    assert any(s in "dbt/dbt_packages/dbt_utils/macros/x.sql"
               for s in adapters.IGNORED_SEGMENTS)
