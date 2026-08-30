"""The rate was in the customer's own purchasing system, behind one `if`.

_resolve_board_sheet_rate_gbp_per_m2 derives a live GBP/m2 for a sheet material from the
current UDEF parts catalogue — plain stock only, median of the real rows, tracking price
changes rather than a stale config table. It opened with:

    # Only HIPS is sourced this way for now; other boards keep their existing path.
    if "HIPS" not in _mat_u:
        return None

Their existing path is an LLM market guess. 11650-04 is what that costs: four ABS/PETG panels
the engine holds no rate for, costed at GBP 175.01, 244.97 and 114.98 a sheet for the same
nominal material, TWO BLOCKING invariants (material_has_no_rate_in_this_engine,
price_not_reproducible) and a handed pair that cannot agree because the guess is keyed per
gauge — 2.0 and 2.2 fetch two different guesses for one panel.

Everything below that gate is material-agnostic already: the plain-stock exclusions, the
'L x W x Tmm' parse, the tiny-offcut floor, the median, the outlier cap. One `if` was the
whole thing, and a rule that names a material is what this engine is not supposed to contain.

TWO REAL HAZARDS IN GENERALISING IT, both guarded here:

  * THE CACHE KEY. It held thickness ALONE, which was correct while exactly one material could
    reach it and silently wrong the moment a second could — 2mm ABS handed the 2mm HIPS rate,
    from a cache hit, under a basis string naming the wrong material.

  * THE SEARCH TOKEN. SQL LIKE cannot say "word boundary", so '%ABS%' returns every ABSORBER
    in the catalogue and a median built from those is not wrong-looking, just wrong.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402


# ── which word the catalogue is asked for ────────────────────────────────────────────

@pytest.mark.parametrize("material,expected", [
    ("HIPS", "HIPS"),                       # the one material that used to work
    ("3MM CLEAR PETG SHEET", "PETG"),       # colour and form are not the material
    ("6MM ABS", "ABS"),
    ("2MM PETG", "PETG"),                   # as a DXF filename spells it
    ("CLEAR POLYCARBONATE", "POLYCARBONATE"),
    ("MR MDF", "MDF"),                      # the exact-match set used to fail on this
    ("MILD STEEL", None),                   # not costed in the Other Sheet block at all
    ("STAINLESS STEEL 304", None),
    ("", None),
    (None, None),
])
def test_the_catalogue_is_asked_for_the_material_and_not_its_description(material, expected):
    assert estimator._sheet_catalogue_token(material) == expected


def test_the_longest_word_wins_so_poly_does_not_match_three_plastics():
    """POLY is a token in the block classifier because it catches polycarbonate, polystyrene
    and polypropylene. As a CATALOGUE SEARCH it would pool all three into one median."""
    assert estimator._sheet_catalogue_token("CLEAR POLYCARBONATE") == "POLYCARBONATE"
    assert estimator._sheet_catalogue_token("POLYPROPYLENE") == "POLYPROPYLENE"
    # Two real words, neither a form or a colour: the material is the longer one. HIGH IMPACT
    # ACRYLIC looked up as HIGH would return whatever else the catalogue calls high-something.
    assert estimator._sheet_catalogue_token("HIGH IMPACT ACRYLIC") == "ACRYLIC"


def test_the_classifier_that_picks_the_workbook_block_decides_this_too():
    """A token list here would be a SECOND classifier beside is_other_sheet_material, and two
    classifiers disagreeing about one part is the defect family this codebase keeps finding —
    _is_board existed twice and the two disagreed on 'MR MDF' and '6MM ABS'."""
    import costed_facts
    for token in costed_facts._PLASTIC_SHEET_TOKENS + costed_facts._BOARD_TIMBER_TOKENS:
        material = f"6MM {token.strip()} SHEET"
        assert costed_facts.is_other_sheet_material(material)
        got = estimator._sheet_catalogue_token(material)
        # A MATERIAL NAMED ONLY BY ITS FORM HAS NOTHING TO LOOK UP. "6MM BOARD SHEET" is
        # costed in the Other Sheet block — correctly — and is not the name of a stock item:
        # searching the catalogue for BOARD would pool MDF, plywood, foam board and MFC into
        # one median and call it this part's rate. None is the honest answer, and it falls
        # back to exactly what the engine did before.
        # WOOD survives and BOARD does not, which is right: the whole-word match means
        # \bWOOD\b never matches PLYWOOD or HARDWOOD, so it is a real lookup, while BOARD
        # names a form that four different stock materials share.
        if token.strip() in {"BOARD"}:
            assert got is None, f"{material} has no material name to search on"
        else:
            assert got is not None, material


def test_a_material_named_only_by_its_form_yields_no_rate_rather_than_a_wrong_one():
    for vague in ("BOARD", "6MM SHEET", "PLASTIC SHEET STOCK", "CLEAR SHEET"):
        assert estimator._sheet_catalogue_token(vague) is None, vague


# ── the cache cannot hand one material another's rate ────────────────────────────────

def test_the_cache_is_keyed_on_material_and_gauge_not_gauge_alone(monkeypatch):
    """THE HAZARD OF GENERALISING IT. Keyed on thickness alone, the first material to be
    looked up at 2.0mm would answer for every other material at 2.0mm — from a cache hit, so
    no query, no sample count, and a basis string naming the wrong material."""
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("HIPS", 2.0)] = 11.50
    # ABS at the same gauge must NOT be answered from the HIPS entry. With no database
    # reachable in the test environment the lookup returns None, which is the honest answer —
    # what must never happen is 11.50.
    got = estimator._resolve_board_sheet_rate_gbp_per_m2("ABS", 2.0)
    assert (got or {}).get("rate_gbp_per_m2") != 11.50


def test_a_cached_rate_is_returned_for_the_material_it_was_measured_for():
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("PETG", 2.2)] = 18.75
    got = estimator._resolve_board_sheet_rate_gbp_per_m2("2.2MM CLEAR PETG", 2.2)
    assert got is not None
    assert got["rate_gbp_per_m2"] == 18.75
    assert got["material_token"] == "PETG"
    assert "petg" in got["basis"]


def test_a_cached_absence_is_remembered_as_an_absence():
    """None means the catalogue was asked and holds nothing. Re-querying on every part of
    every job for a material the customer does not stock is the cost this cache exists to
    avoid, and treating the miss as 'not yet asked' would defeat it."""
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("ABS", 3.0)] = None
    assert estimator._resolve_board_sheet_rate_gbp_per_m2("6MM ABS", 3.0) is None


def test_a_gauge_it_has_not_seen_is_not_answered_from_another_gauge():
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("PETG", 2.2)] = 18.75
    got = estimator._resolve_board_sheet_rate_gbp_per_m2("PETG", 5.0)
    assert (got or {}).get("rate_gbp_per_m2") != 18.75


# ── it still refuses to invent anything ──────────────────────────────────────────────

def test_a_material_the_block_does_not_cost_is_never_looked_up():
    estimator._SHEET_RATE_CACHE.clear()
    # Poisoned so a lookup that ignored the classifier would return a number.
    estimator._SHEET_RATE_CACHE[("STEEL", 2.0)] = 99.99
    assert estimator._resolve_board_sheet_rate_gbp_per_m2("MILD STEEL", 2.0) is None


def test_no_thickness_is_no_rate():
    """The catalogue rows are per gauge. Averaging across gauges would produce a number for
    every material and a correct one for none."""
    estimator._SHEET_RATE_CACHE.clear()
    assert estimator._resolve_board_sheet_rate_gbp_per_m2("PETG", None) is None


def test_the_query_is_parameterised():
    """The token comes from a material string read off a drawing, and a drawing is external
    input like any other. Asserted on the source because the database is not reachable here —
    the alternative is no check at all on a string that reaches SQL."""
    import inspect
    src = inspect.getsource(estimator._resolve_board_sheet_rate_gbp_per_m2)
    assert "LIKE ?" in src, "the search token is formatted into the SQL"
    assert 'f"%{_token}%"' in src or "(f\"%{_token}%\"," in src


def _row(desc, cost):
    return ("CODE", desc, cost)


def test_the_token_is_matched_as_a_whole_word():
    """'%ABS%' returns every ABSORBER and GLASSBOARD in the catalogue. A median built from
    those is not wrong-looking, it is simply wrong, and nothing on the sheet would say so.

    Exercised, not grepped. This was a source check, and a mutant that deleted the whole-word
    filter passed it — the constant was still defined, just never used.
    """
    rows = [
        _row("2440 x 1220 x 2.0mm ABS SHEET", 24.40),          # kept
        # PRICED PLAUSIBLY ON PURPOSE. At GBP 500 these fall out on the GBP 60/m2 outlier
        # cap instead, and the test then passes with the whole-word filter deleted — which is
        # exactly what a mutant proved. A decoy has to be excluded by the guard under test.
        _row("2440 x 1220 x 2.0mm SOUND ABSORBER PANEL", 60.00),    # must not count
        _row("2440 x 1220 x 2.0mm GLASSBOARD ABSOLUTE", 90.00),     # must not count
    ]
    rates = estimator._plain_stock_rates_gbp_per_m2(rows, "ABS", 2.0)
    assert len(rates) == 1
    assert rates[0] == pytest.approx(24.40 / (2.44 * 1.22), rel=1e-6)


def test_printed_and_mirrored_stock_is_not_a_sheet_rate():
    rows = [
        _row("2440 x 1220 x 3.0mm PETG SHEET", 30.00),
        # Under the GBP 60/m2 cap, so only the premium-stock filter can exclude them.
        _row("2440 x 1220 x 3.0mm PETG SHEET DIGITALLY PRINTED", 90.00),
        _row("2440 x 1220 x 3.0mm MIRROR PETG", 80.00),
    ]
    assert len(estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 3.0)) == 1


def test_another_gauge_is_another_rate():
    rows = [
        _row("2440 x 1220 x 2.0mm PETG SHEET", 24.00),
        _row("2440 x 1220 x 5.0mm PETG SHEET", 60.00),
    ]
    assert len(estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 2.0)) == 1


def test_a_tiny_offcut_does_not_set_the_rate():
    """A 200 x 150 remnant at GBP 6 is GBP 200/m2 and would drag a median a long way."""
    # GBP 30/m2 — a plausible rate, so the outlier cap does not do this guard's job for it.
    rows = [_row("200 x 150 x 2.0mm PETG OFFCUT", 0.90)]
    assert estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 2.0) == []


def test_a_premium_outlier_does_not_set_the_rate():
    """A row that survives every name filter and is still nothing like sheet stock — a
    laminated or specially-finished panel the exclusion words do not name. GBP 60/m2 is the
    ceiling on plain stock, and one row above it pulls a small median a long way."""
    rows = [
        _row("2440 x 1220 x 2.0mm PETG SHEET", 24.40),
        _row("2440 x 1220 x 2.0mm PETG SHEET SPECIAL LAMINATED", 400.00),
    ]
    rates = estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 2.0)
    assert len(rates) == 1
    assert max(rates) <= estimator._SHEET_RATE_MAX_GBP_PER_M2


def test_a_zero_or_negative_cost_is_not_a_free_sheet():
    rows = [_row("2440 x 1220 x 2.0mm PETG SHEET", 0.0)]
    assert estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 2.0) == []


def test_a_row_with_no_dimensions_is_skipped_rather_than_guessed():
    rows = [_row("PETG SHEET ASSORTED", 30.00)]
    assert estimator._plain_stock_rates_gbp_per_m2(rows, "PETG", 2.0) == []


def test_the_hips_path_that_worked_still_works():
    """HIPS is the one material this has been pricing correctly on real jobs. A generalisation
    that changed its answer would be trading a known-good rate for a wider one."""
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("HIPS", 2.0)] = 11.50
    got = estimator._resolve_board_sheet_rate_gbp_per_m2("HIPS", 2.0)
    assert got["rate_gbp_per_m2"] == 11.50
    assert got["material_token"] == "HIPS"
