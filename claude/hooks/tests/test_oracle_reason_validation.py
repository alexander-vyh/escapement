"""Oracle-quality tests for the `# oracle:` override substance bar.

Business invariant
------------------
A `# oracle: <reason>` override exempts a flagged test file from
implementation-echo detection ONLY when the reason names an INDEPENDENT
source of truth. A reason that is circular (its only specific referents are
the file's own asserted literals), a placeholder, or too short must NOT
exempt the file — otherwise the override is mock bureaucracy: a string that
satisfies the gate without doing the underlying work (gate-design.md Rule 3).

Fragile implementation this suite must reject
---------------------------------------------
A LENGTH-ONLY bar (`len(reason) >= 20`). The real-world circular reason that
motivated this change is 70+ characters, so a length-only check ACCEPTS it.
`test_real_circular_reason_is_rejected` is the negative control that kills
that fragile implementation: it must come back "circular", not None.
"""

import importlib.util
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
MODULE_PATH = TEST_DIR / "oracle_reason_validation.py"
if not MODULE_PATH.exists():
    MODULE_PATH = TEST_DIR.parent / "oracle_reason_validation.py"
spec = importlib.util.spec_from_file_location("oracle_reason_validation", MODULE_PATH)
orv = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["oracle_reason_validation"] = orv
spec.loader.exec_module(orv)


# --- NEGATIVE CONTROLS: reasons that must be REJECTED ------------------------

def test_real_circular_reason_is_rejected():
    """The exact reason from the investigation (cro dw-report-domain test:292).

    Its only specific referents — backlog_open_14d, pct_automated — are
    asserted string literals in the same file. A length-only bar would pass
    this 70-char reason; the substance bar must classify it 'circular'.
    """
    reason = "the field-name literals (e.g. backlog_open_14d, pct_automated) are the"
    asserted = orv.asserted_tokens({"backlog_open_14d", "pct_automated", "month_start"})
    assert orv.validate_oracle_reason(reason, asserted) == "circular"


def test_pure_boilerplate_reason_is_rejected():
    """No specific referent at all — only oracle/test descriptor vocabulary."""
    reason = "these literals are the asserted oracle constant values"
    assert orv.validate_oracle_reason(reason, set()) == "circular"


def test_reason_naming_only_asserted_literals_is_rejected():
    reason = "the pct_automated and automated_grants columns are the oracle here"
    asserted = orv.asserted_tokens({"pct_automated", "automated_grants"})
    assert orv.validate_oracle_reason(reason, asserted) == "circular"


def test_too_short_reason_is_rejected():
    assert orv.validate_oracle_reason("tbd", set()) == "too-short"
    assert orv.validate_oracle_reason("see code", set()) == "too-short"


def test_placeholder_reason_is_rejected():
    # >= 20 chars so it clears the length bar, but is still a null pattern.
    assert orv.validate_oracle_reason("n/a n/a n/a n/a n/a n/a", set()) == "placeholder"


# --- POSITIVE CONTROLS: reasons that must be ACCEPTED (return None) ----------

def test_independent_external_referent_is_accepted():
    """Names a source of truth OUTSIDE the test's own asserted literals."""
    reason = "cross-checked against the upstream Salesforce report export totals"
    asserted = orv.asserted_tokens({"pct_automated"})
    assert orv.validate_oracle_reason(reason, asserted) is None


def test_reason_mentioning_a_literal_but_also_external_is_accepted():
    """A single external referent rescues a reason — the escape path must stay
    usable for legitimate overrides (gate-design.md Rule 1 / Flexibility).
    """
    reason = "pct_automated equals automated_grants over total_grants from the upstream dbt model"
    asserted = orv.asserted_tokens({"pct_automated", "automated_grants", "total_grants"})
    assert orv.validate_oracle_reason(reason, asserted) is None


def test_consumer_contract_justification_is_accepted():
    """'these column names ARE the contract' is fine when it explains WHY
    independently (a consumer-facing schema contract), not just self-reference.
    """
    reason = "these column names are the public schema contract downstream consumers depend on"
    asserted = orv.asserted_tokens({"month_start", "total_grants", "pct_automated"})
    assert orv.validate_oracle_reason(reason, asserted) is None


# --- tokenizer helper -------------------------------------------------------

def test_asserted_tokens_extracts_identifiers_from_literals():
    toks = orv.asserted_tokens({"pct_automated", "backlog_open_14d"})
    assert "pct_automated" in toks
    assert "backlog_open_14d" in toks


# --- partition_overrides: honored vs rejected -------------------------------

def test_partition_rejects_circular_keeps_independent():
    overrides = {
        "tests/circular.py": ["the field-name literals (e.g. pct_automated) are the"],
        "tests/independent.py": ["cross-checked against the upstream Salesforce report export"],
    }
    asserted_by_file = {
        "tests/circular.py": orv.asserted_tokens({"pct_automated"}),
        "tests/independent.py": orv.asserted_tokens({"pct_automated"}),
    }

    valid, rejected = orv.partition_overrides(overrides, asserted_by_file)

    assert valid == {"tests/independent.py"}
    assert set(rejected) == {"tests/circular.py"}
    assert rejected["tests/circular.py"][0][1] == "circular"


def test_partition_file_with_any_valid_reason_is_honored():
    """One acceptable reason among several rescues the file (escape stays usable)."""
    overrides = {
        "tests/mixed.py": [
            "the pct_automated literal is the oracle",                 # circular
            "verified against the finance board deck quarterly totals",  # independent
        ]
    }
    asserted_by_file = {"tests/mixed.py": orv.asserted_tokens({"pct_automated"})}

    valid, rejected = orv.partition_overrides(overrides, asserted_by_file)

    assert valid == {"tests/mixed.py"}
    assert rejected == {}
