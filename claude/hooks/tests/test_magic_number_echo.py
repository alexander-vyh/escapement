"""Oracle for the magic-number / business-constant echo detector.

Business invariant
------------------
A test that asserts a FORMATTED numeric token (e.g. "91%", "$5M", "3.2x")
which also appears INSIDE a source description string is a documentation
echo: it re-asserts a number that lives in prose rather than verifying a
computed value. Flag it. A legitimate constant assertion (`assert score ==
91`) and an unformatted number (a bare int, a year) must NOT be flagged.

Independent discriminator
-------------------------
The same formatted numeric token appears (a) as a substring of a SOURCE
file's string literal, AND (b) as a whole asserted string literal in a TEST.
A formatted token is one carrying a significance marker — %, currency, a
unit (x/k/m/b), a decimal, or a thousands comma — so bare ints/years are out.

Fragile implementations this suite must reject
----------------------------------------------
1. "flag any shared number, including bare ints" — killed by
   `test_bare_int_constant_assertion_not_flagged` and
   `test_year_in_string_not_flagged` (no marker -> not a formatted number).
2. "require the source occurrence to be a whole string literal" — killed by
   `test_percent_embedded_in_sentence_is_flagged`: the number lives INSIDE a
   prose sentence, not as a standalone literal.
"""

import importlib.util
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
MODULE_PATH = TEST_DIR / "magic_number_echo.py"
if not MODULE_PATH.exists():
    MODULE_PATH = TEST_DIR.parent / "magic_number_echo.py"
spec = importlib.util.spec_from_file_location("magic_number_echo", MODULE_PATH)
mne = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["magic_number_echo"] = mne
spec.loader.exec_module(mne)


# --- token classification ---------------------------------------------------

def test_is_formatted_number_accepts_marked_tokens():
    for tok in ("91%", "12.5%", "$5M", "3.2x", "1,234", "€10k", "2.3B"):
        assert mne.is_formatted_number(tok), tok


def test_is_formatted_number_rejects_bare_and_nonnumeric():
    for tok in ("91", "2024", "5", "", "abc", "v2", "id_42"):
        assert not mne.is_formatted_number(tok), tok


def test_formatted_numbers_in_extracts_from_prose():
    assert mne.formatted_numbers_in("standing snapshot reads ~91% because older") == {"91%"}
    assert mne.formatted_numbers_in("grew $5M in Q3 at 3.2x pace") == {"$5M", "3.2x"}


def test_formatted_numbers_in_ignores_bare_ints_and_years():
    assert mne.formatted_numbers_in("version 2024 had 91 rows and id 5") == set()


# --- NEGATIVE CONTROLS: must NOT flag ---------------------------------------

def test_bare_int_constant_assertion_not_flagged():
    source = {"src/score.py": "PASS_THRESHOLD = 91\n"}
    tests = {"tests/test_score.py": "def test_pass():\n    assert score == 91\n"}
    assert mne.find_magic_number_echoes(source, tests) == []


def test_year_in_string_not_flagged():
    source = {"src/app.py": 'BANNER = "release version 2024 is live"\n'}
    tests = {"tests/test_app.py": 'def test_year():\n    assert "2024" in banner\n'}
    assert mne.find_magic_number_echoes(source, tests) == []


def test_source_only_number_not_flagged():
    source = {"src/m.py": 'DESC = "snapshot reads ~91% today"\n'}
    tests = {"tests/test_m.py": "def test_x():\n    assert compute() > 0\n"}
    assert mne.find_magic_number_echoes(source, tests) == []


def test_test_only_number_not_flagged():
    source = {"src/m.py": "RATE = compute_rate()\n"}
    tests = {"tests/test_m.py": 'def test_x():\n    assert "91%" in render()\n'}
    assert mne.find_magic_number_echoes(source, tests) == []


def test_different_numbers_not_flagged():
    source = {"src/m.py": 'DESC = "snapshot reads ~91% today"\n'}
    tests = {"tests/test_m.py": 'def test_x():\n    assert "92%" in describe()\n'}
    assert mne.find_magic_number_echoes(source, tests) == []


# --- POSITIVE CONTROLS: must flag -------------------------------------------

def test_percent_embedded_in_sentence_is_flagged():
    """The real '91%' shape: the number lives INSIDE a prose source string and
    is asserted whole in the test. This is the documentation echo.
    """
    source = {
        "src/metric_descriptions.py": (
            'PCT_AUTOMATED = "all-history standing snapshot reads ~91% because it '
            'still carries older manual grants"\n'
        )
    }
    tests = {
        "tests/test_report_domains.py": (
            'def test_pct_automated():\n'
            '    assert "91%" in describe("dw_access_provisioning_monthly", "pct_automated")\n'
        )
    }
    findings = mne.find_magic_number_echoes(source, tests)
    assert len(findings) == 1
    assert findings[0].filepath == "tests/test_report_domains.py"
    assert findings[0].token == "91%"
    assert "src/metric_descriptions.py" in findings[0].sources


def test_currency_token_is_flagged():
    source = {"src/blurb.py": 'GROWTH = "revenue grew $5M in Q3 of last year"\n'}
    tests = {"tests/test_blurb.py": 'def test_growth():\n    assert "$5M" in blurb()\n'}
    findings = mne.find_magic_number_echoes(source, tests)
    assert len(findings) == 1
    assert findings[0].token == "$5M"


def test_multiplier_token_is_flagged():
    source = {"src/perf.py": 'NOTE = "the new path is 3.2x faster than baseline"\n'}
    tests = {"tests/test_perf.py": 'def test_perf():\n    assert "3.2x" in note()\n'}
    findings = mne.find_magic_number_echoes(source, tests)
    assert len(findings) == 1
    assert findings[0].token == "3.2x"
