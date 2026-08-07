"""Estimating would rather correct a low-confidence number than fill a blank.

The workbook used to keep an AI market estimate off the price column entirely. Every
reason given for that turned on the figure CHANGING between runs — the same part came
back at GBP 35.62, 95.62, 75.62 and 85.62 on four consecutive runs of one job.

Uncertainty and instability are different faults. Uncertainty can be declared: say where
a number came from and how far to trust it, and an estimator can weigh it. Instability
cannot be declared away — two people reading the same job on the same day would disagree
about what it says — and it was instability that disqualified the figure.

So a generated price is now asked once per specification and stored. Once it holds still
it prices the line, tagged INDICATIVE. One that still cannot be reproduced is still kept
off the total, because that is the fault nobody can work around.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import estimator_inputs  # noqa: E402
import generated_price_cache as gpc  # noqa: E402
import price_provenance  # noqa: E402


_SPEC = {"material": "Mild Steel", "description": "BRACKET", "thickness_mm": 1.5,
         "part_code": "12392-02-17G", "quantity": 180}


# ---------------------------------------------------------------------------
# The same question gets the same answer
# ---------------------------------------------------------------------------
def test_the_model_is_asked_once_and_the_answer_reused(tmp_path):
    calls = []

    def _compute():
        calls.append(1)
        return {"found": True, "price_gbp": 35.62 + 20.0 * len(calls),
                "source_type": "llm_market_estimate"}

    first = gpc.cached_estimate(_SPEC, "xai", "grok-4.3", _compute,
                                cache_dir=str(tmp_path))
    second = gpc.cached_estimate(_SPEC, "xai", "grok-4.3", _compute,
                                 cache_dir=str(tmp_path))

    assert len(calls) == 1, "the second run must not ask again"
    assert first["price_gbp"] == second["price_gbp"] == 55.62
    assert second["price_from_cache"] is True
    assert second["price_is_reproducible"] is True


def test_spelling_and_spacing_do_not_split_one_question_into_two(tmp_path):
    """"MILD STEEL" and " Mild  Steel " are the same part. A cache that thinks otherwise
    asks twice and gets two answers, which is the whole fault it exists to remove."""
    calls = []

    def _compute():
        calls.append(1)
        return {"found": True, "price_gbp": 10.0 * len(calls),
                "source_type": "llm_market_estimate"}

    gpc.cached_estimate(dict(_SPEC, material="Mild Steel"), "xai", "m", _compute,
                        cache_dir=str(tmp_path))
    gpc.cached_estimate(dict(_SPEC, material="  MILD   STEEL "), "xai", "m", _compute,
                        cache_dir=str(tmp_path))
    assert len(calls) == 1


def test_a_different_part_is_a_different_question(tmp_path):
    calls = []

    def _compute():
        calls.append(1)
        return {"found": True, "price_gbp": 1.0, "source_type": "llm_market_estimate"}

    gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path))
    gpc.cached_estimate(dict(_SPEC, thickness_mm=3.0), "xai", "m", _compute,
                        cache_dir=str(tmp_path))
    assert len(calls) == 2


def test_a_new_model_or_prompt_version_is_a_new_question(tmp_path):
    calls = []

    def _compute():
        calls.append(1)
        return {"found": True, "price_gbp": 1.0, "source_type": "llm_market_estimate"}

    gpc.cached_estimate(_SPEC, "xai", "grok-4.3", _compute, cache_dir=str(tmp_path))
    gpc.cached_estimate(_SPEC, "xai", "grok-5", _compute, cache_dir=str(tmp_path))
    assert len(calls) == 2


def test_a_failure_is_not_remembered_as_a_fact_about_the_part(tmp_path):
    """Tomorrow's run must ask again rather than inherit today's network problem."""
    calls = []

    def _compute():
        calls.append(1)
        return {"found": False, "error": "no API key"}

    gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path))
    out = gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path))
    assert len(calls) == 2
    assert out["price_is_reproducible"] is False


def test_refresh_asks_again_and_replaces_the_stored_answer(tmp_path):
    calls = []

    def _compute():
        calls.append(1)
        return {"found": True, "price_gbp": 10.0 * len(calls),
                "source_type": "llm_market_estimate"}

    gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path))
    out = gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path),
                              refresh=True)
    assert len(calls) == 2 and out["price_gbp"] == 20.0
    again = gpc.cached_estimate(_SPEC, "xai", "m", _compute, cache_dir=str(tmp_path))
    assert again["price_gbp"] == 20.0, "the refreshed answer is the stored one"


def test_the_stored_entry_is_readable(tmp_path):
    """One inspectable JSON per specification. Deleting it asks the question again;
    nothing about the cache should need explaining to whoever finds it."""
    gpc.cached_estimate(_SPEC, "xai", "m",
                        lambda: {"found": True, "price_gbp": 7.5,
                                 "source_type": "llm_market_estimate"},
                        cache_dir=str(tmp_path))
    files = list(Path(tmp_path).glob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text(encoding="utf-8"))
    assert entry["result"]["price_gbp"] == 7.5
    assert entry["spec"]["PART_CODE" if "PART_CODE" in entry["spec"] else "part_code"]
    assert entry["created_utc"]


# ---------------------------------------------------------------------------
# What the workbook now does with it
# ---------------------------------------------------------------------------
def test_a_reproducible_estimate_prices_the_line():
    """The change estimating asked for: a low-confidence number to correct, not a gap."""
    part = {"part_number": "12392-02-17G", "_price_is_reproducible": True}
    assert estimator_inputs.indicative_price_to_withhold(part, True, 55.62) is None


def test_an_unrepeatable_estimate_is_still_kept_off_the_total():
    """Mutation guard on the rule above. A figure that answers differently every time it
    is asked cannot be weighed, because there is nothing stable to weigh."""
    part = {"part_number": "12392-02-17G"}
    assert estimator_inputs.indicative_price_to_withhold(part, True, 55.62) == 55.62


def test_a_catalogue_price_was_never_withheld_and_still_is_not():
    part = {"part_number": "BI-BOLTBZP"}
    assert estimator_inputs.indicative_price_to_withhold(part, False, 0.83) is None


# ---------------------------------------------------------------------------
# The stamp the decision reads
# ---------------------------------------------------------------------------
def test_the_reproducible_flag_is_read_from_a_stamp():
    assert price_provenance.stamp_is_reproducible({"price_is_reproducible": True}) is True
    assert price_provenance.stamp_is_reproducible(
        {"selected": {"price_is_reproducible": True}}) is True


def test_an_unstamped_price_is_not_assumed_reproducible():
    """Absence of evidence is not the evidence the price column needs."""
    assert price_provenance.stamp_is_reproducible({}) is False
    assert price_provenance.stamp_is_reproducible({"source_class": "ai_estimate"}) is False
    assert price_provenance.stamp_is_reproducible(None) is False


def test_a_line_with_no_generated_price_is_reproducible_by_nature():
    """A catalogue rate, a spreadsheet cell and a historical line all repeat perfectly.
    The question only ever arises for a figure the model composed."""
    import wb_populate

    assert wb_populate._price_is_reproducible({"part_number": "X"}) is True
