"""Oracle for repo_outcome.resolve() / authorizes_auto_merge() — the reader for
`.escapement/repo.json`, the per-project options manifest (repo-outcome-authorization).

Business invariant: a repo's auto-merge authorization is honored ONLY when it is
explicitly and validly declared. Absent, malformed, or invalid declarations resolve to
the CONSERVATIVE default (intended_outcome=pr-opened, auto_merge_on_green=False) — an
unconfigured repo must behave exactly as today. A missing or broken file must never be
treated as authorization to merge/deploy live (design anti-metric #2).

Oracle quality:
  - NEGATIVE CONTROLS:
      * absent file        -> not authorized, source=default-absent
      * malformed JSON     -> not authorized, source=default-malformed, warning set
      * invalid outcome    -> not authorized, source=default-invalid, warning set
      * inconsistent decl  -> auto_merge_on_green=true but intended_outcome=pr-opened
                              => authorizes_auto_merge() is False (consistency guard)
  - POSITIVE CONTROL: valid merged-and-deployed + auto_merge_on_green:true
                      -> authorized, source=declared (auth not accidentally dropped)
  - FRAGILE IMPL REJECTED: a reader that returns authorized whenever the
    `auto_merge_on_green` key is truthy — the malformed case, the invalid-outcome
    case, and the pr-opened+true consistency case must all fail it.
"""
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import repo_outcome as ro


def _write(tmp_path, obj):
    d = tmp_path / ".escapement"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "repo.json"
    if isinstance(obj, str):
        p.write_text(obj)
    else:
        p.write_text(json.dumps(obj))
    return tmp_path


# --- POSITIVE CONTROL ------------------------------------------------------

def test_valid_merged_and_deployed_authorizes(tmp_path):
    root = _write(tmp_path, {
        "intended_outcome": "merged-and-deployed",
        "auto_merge_on_green": True,
        "deploy": {"surface": "Cloud Run exec dashboard"},
        "confirm_class": [],
    })
    out = ro.resolve(root)
    assert out.source == "declared"
    assert out.intended_outcome == "merged-and-deployed"
    assert out.auto_merge_on_green is True
    assert out.warning is None
    assert ro.authorizes_auto_merge(out) is True
    assert out.deploy == {"surface": "Cloud Run exec dashboard"}


def test_valid_merged_level_also_authorizes(tmp_path):
    root = _write(tmp_path, {"intended_outcome": "merged", "auto_merge_on_green": True})
    assert ro.authorizes_auto_merge(ro.resolve(root)) is True


# --- NEGATIVE CONTROL: absent (the conservative default = today's behavior) ---

def test_absent_file_is_conservative_default(tmp_path):
    out = ro.resolve(tmp_path)  # no .escapement/repo.json written
    assert out.source == "default-absent"
    assert out.intended_outcome == "pr-opened"
    assert out.auto_merge_on_green is False
    assert ro.authorizes_auto_merge(out) is False


# --- NEGATIVE CONTROL: malformed (fail-safe, never authorize on broken file) ---

def test_malformed_json_falls_back_with_warning(tmp_path):
    root = _write(tmp_path, "{ this is not valid json ")
    out = ro.resolve(root)
    assert out.source == "default-malformed"
    assert out.auto_merge_on_green is False
    assert out.warning is not None and out.warning != ""
    assert ro.authorizes_auto_merge(out) is False


def test_non_object_json_falls_back(tmp_path):
    root = _write(tmp_path, json.dumps(["not", "an", "object"]))
    out = ro.resolve(root)
    assert out.source == "default-malformed"
    assert ro.authorizes_auto_merge(out) is False


# --- NEGATIVE CONTROL: invalid intended_outcome value ---

def test_invalid_intended_outcome_falls_back_with_warning(tmp_path):
    root = _write(tmp_path, {"intended_outcome": "yolo", "auto_merge_on_green": True})
    out = ro.resolve(root)
    assert out.source == "default-invalid"
    assert out.warning is not None
    assert ro.authorizes_auto_merge(out) is False


# --- NEGATIVE CONTROL: consistency guard (the subtle one) ---

def test_auto_merge_true_but_outcome_only_pr_opened_does_not_authorize(tmp_path):
    # A repo may not auto-merge if its declared intended outcome is only pr-opened.
    # This is the consistency guard: authorization requires BOTH the flag AND an
    # outcome at or above 'merged'. A fragile reader keying only on the boolean fails here.
    root = _write(tmp_path, {"intended_outcome": "pr-opened", "auto_merge_on_green": True})
    out = ro.resolve(root)
    assert out.source == "declared"          # it IS a valid declaration
    assert out.auto_merge_on_green is True    # the field is faithfully read
    assert ro.authorizes_auto_merge(out) is False  # but it does not authorize


# --- ladder / helper sanity ---

def test_ladder_ordering_exposed(tmp_path):
    assert ro.INTENDED_OUTCOME_LADDER.index("committed") < \
           ro.INTENDED_OUTCOME_LADDER.index("pr-opened") < \
           ro.INTENDED_OUTCOME_LADDER.index("merged") < \
           ro.INTENDED_OUTCOME_LADDER.index("merged-and-deployed")
