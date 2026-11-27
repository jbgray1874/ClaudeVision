"""A piano hinge is not whatever one-word hinge history holds.

12645 DRS External Shelter (Tesco), 19:17 book, 28 Sep 2026: Estimate row 14 charged
"piano hinge  HINGE" x1 at GBP 0.26, supplier "Historical quote", provenance
"catalogue — historical_quote_material_line". The door it hangs is 2,020 mm tall.

12645-03GA's parts list reads `4 | piano hinge | HINGE | 1`. The qualifier is in the code
column; the historical lookup scored the DESCRIPTION alone, {HINGE}, so the least specific
hinge in history won at 100% (D-323). The code column's words now join the query when that
column holds a name, not a code, and a historical line must contain them.

Deliberately narrow: no one-word guard and no new coverage threshold. The review showed a
coverage rule would move matches this rung was tuned on ("2.4x6mm DOME RIVET, ALU" against
"DOME RIVET" at 0.50). The historical rows below are illustrative.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pricing_service as ps                                        # noqa: E402
from pricing_service import PricingService                          # noqa: E402

HINGE_ROW = {"part_number": "piano hinge", "description": "HINGE",
             "normalized_material": "MILD STEEL", "page_roles": ["bought_in"]}


def _history(*lines):
    """A PricingService with no database whose historical table holds `lines`
    (description, unit price), fetched as the SQL fetches: any asked word, as a substring."""
    svc = object.__new__(PricingService)
    asked: list = []

    def _all(query, params=None):
        asked.append((query, list(params or [])))
        if "historical_quote_material_line" not in query:
            return []
        words = [str(w).upper() for w in (params or [])[1:]]
        return [(d, p, p, "D", "2025-03-01", None, None) for d, p in lines
                if any(w in d.upper() for w in words)]

    svc._fetch_all_with_retry = _all
    svc._fetch_one_with_retry = lambda query, params=None: None
    return svc, asked


def test_the_code_column_adds_its_words_when_it_holds_a_name():
    assert ps.code_column_words(HINGE_ROW, PricingService._tokenize) == {"PIANO"}


@pytest.mark.parametrize("code", ["12645-03-01M", "FIXING41", "466122", "BI-PEMSTUD",
                                  "FIXING", "P/P", "TBC"])
def test_a_code_a_class_word_a_mint_or_a_placeholder_adds_no_words(code):
    assert ps.code_column_words({"part_number": code, "description": "HINGE"},
                                PricingService._tokenize) == set()


def test_a_one_word_hinge_line_does_not_price_the_piano_hinge(capsys):
    svc, asked = _history(("HINGE", 0.26), ("BUTT HINGE 50MM", 0.45))
    assert svc._get_historical_rag(dict(HINGE_ROW)) is None
    assert any("PIANO" in [str(p).upper() for p in params] for _, params in asked), \
        "the qualifier must reach the historical query"
    out = capsys.readouterr().out
    assert "does not contain PIANO" in out and "not used for" in out


def test_a_piano_hinge_line_in_history_still_prices_it():
    svc, _ = _history(("HINGE", 0.26), ("PIANO HINGE", 14.50))
    got = svc._get_historical_rag(dict(HINGE_ROW))
    assert got and got["unit_price_gbp"] == 14.50


@pytest.mark.parametrize("part,line,price", [
    # the matches this rung was tuned on must not move (pricing_service's own comment)
    ({"part_number": "FIXING", "description": "2.4x6mm DOME RIVET, ALU",
      "normalized_material": "ALUMINIUM"}, "DOME RIVET", 0.03),
    ({"part_number": "12120-01-09", "description": "50cm LOOM LIGHTING ELECTRICS",
      "normalized_material": "STAINLESS_STEEL_304"}, "ELECTRICS - 50cm LOOM", 3.10),
    ({"part_number": "MAGNET", "description": "MAGNET", "normalized_material": ""},
     "MAGNET", 0.40),
])
def test_the_matches_this_rung_was_tuned_on_do_not_move(part, line, price):
    svc, _ = _history((line, price))
    got = svc._get_historical_rag(dict(part))
    assert got and got["unit_price_gbp"] == price, got


def test_a_historical_match_is_labelled_as_one_on_the_sheet():
    """The label table held "Historical quote match - verify" keyed by SOURCE, and the sheet
    looked it up by CLASS, so the warning was unreachable."""
    import inspect
    import wb_populate as wp
    src = inspect.getsource(wp._price_origin)
    assert "stamp_source_name(best)" in src
    assert wp._ORIGIN_LABELS["historical_quote_material_line"] == "Historical quote match - verify"


def test_a_squashed_code_is_read_for_what_it_adds_not_as_one_word():
    """The 29 Sep run: the shutter's code arrived as ROLLERSHUTTER, the rule required that
    token of the history line, and 'ALLUMINIUM ROLLER SHUTTER DOOR' was refused. The code adds
    nothing beyond "Roller Shutter Door"; the hinge's squashed code still adds PIANO."""
    tok = PricingService._tokenize
    assert ps.code_column_words({"part_number": "ROLLERSHUTTER",
                                 "description": "Roller Shutter Door"}, tok) == set()
    assert ps.code_column_words({"part_number": "PIANOHINGE", "description": "HINGE"}, tok) == {"PIANO"}
    svc, _ = _history(("ALLUMINIUM ROLLER SHUTTER DOOR", 306.16))
    got = svc._get_historical_rag({"part_number": "ROLLERSHUTTER",
                                   "description": "Roller Shutter Door"})
    assert got and got["unit_price_gbp"] == 306.16
    svc, _ = _history(("HINGE", 0.26))
    assert svc._get_historical_rag({"part_number": "PIANOHINGE", "description": "HINGE",
                                    "normalized_material": "MILD STEEL"}) is None
