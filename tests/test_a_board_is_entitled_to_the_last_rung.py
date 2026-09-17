r"""An unpriced board is not an answer. It is the ladder stopping one rung early.

James Gray, 17 September 2026:

    "it's lame not to price the MDF and Tony is sarcastic and will laugh about it."

    "SDI Live will have prices all over the place in it also. SDI does it all the time."

Two separate faults, both of which made a real material with a real measured area read as
having no price while SDI's own money sat on file or a current rate was one lookup away.

ONE - THE CATALOGUE WAS ASKED BY ONE NAME. `_sheet_catalogue_token` takes the longest word
in the material's own name, so a faced board is looked up as "MFMDF". A purchasing system
is written by buyers over years and the same board arrives under whatever the supplier's
invoice called it: "Melamine Faced MDF" on one row, "MFMDF" on the next. One spelling asked,
the other ignored, and the rate the customer already owns is missed. Now every name the
catalogue might hold it under is tried IN ORDER, most specific first, and the first that
answers wins - never pooled, because two spellings can be two different boards.

TWO - RUNG 4 WAS WIRED INTO ONE CHAIN. The researched price - a figure that names its
source, its date, what it is per, and the arithmetic to this line - was built for BOUGHT-IN
lines and reachable only from the bought-in price chain. A board is a material, so after
rung 1 missed it fell off the bottom of the ladder and there was nothing below it. Rung 4
is not a property of being a bought-in. It is the last rung, and every line is entitled to
it.

WHAT DOES NOT CHANGE. The figure still has to be evidenced or it is not used; it is still
labelled rung 4 on every document; the contamination guard still bars anything that came
off an estimator's sheet; and the melamine probe still cannot answer for chipboard.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402

_TRAY = {"part_number": "11908-21-01J", "normalized_material": "MDF",
         "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2,
         "dxf_source_file": "11908-21-01J_9mm MDF+ LAM_REV[A].DXF"}


def _tray(**over):
    return dict(_TRAY, **over)


# ── 1 · every name SDI Live might hold the board under ───────────────────────────────

def test_the_boards_own_name_is_asked_first():
    probes = estimator._sheet_catalogue_probes("MFMDF")
    assert probes[0] == ("MFMDF", None), probes


def test_the_trades_own_spellings_are_asked_after_it():
    probes = estimator._sheet_catalogue_probes("MFMDF")
    assert ("MELAMINE", "MDF") in probes
    assert ("FACED", "MDF") in probes


def test_a_melamine_probe_cannot_answer_for_the_other_family():
    """"MELAMINE" matches melamine-faced chipboard and melamine-faced MDF equally. A
    median across both is one rate answering two questions."""
    mfmdf = dict(estimator._sheet_catalogue_probes("MFMDF"))
    mfc = dict(estimator._sheet_catalogue_probes("MFC"))
    assert mfmdf["MELAMINE"] == "MDF"
    assert mfc["MELAMINE"] == "CHIPBOARD"


def test_a_plain_material_gains_no_synonyms():
    """The control. Plain MDF, steel and acrylic are asked exactly as they always were."""
    assert estimator._sheet_catalogue_probes("MDF") == [("MDF", None)]
    assert estimator._sheet_catalogue_probes("STEEL") == []


# ── 2 · and where the catalogue holds nothing, the last rung answers ─────────────────

class _Research:
    """Stands in for the web/LLM rung. Records the brief it was handed."""

    def __init__(self, **found):
        self.found = found
        self.briefs = []

    def __call__(self, brief):
        self.briefs.append(brief)
        return dict(self.found)


def _no_catalogue(monkeypatch):
    monkeypatch.setattr(estimator, "_resolve_board_sheet_rate_gbp_per_m2",
                        lambda *_a, **_k: None)


def test_a_researched_rate_prices_the_board(monkeypatch):
    """0.1521 m² at £24.50/m² = £3.73, plus 4% scrap = £3.88 a part. Not a blank."""
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research(
        price_gbp=24.50, unit="per_m2",
        source="https://example-merchant.co.uk/mfmdf-9mm",
        quantity_basis="2800x2070 sheet, priced per m2", as_of="2026-09-17"))
    out = estimator.estimate_material(_tray())
    assert out["cost_method"] == "board_rate_researched", out.get("cost_method")
    assert out["cost_per_part_gbp"] == 3.88, out["cost_per_part_gbp"]
    assert out["costing_material_family"] == "MFMDF"


def test_it_is_labelled_for_what_it_is(monkeypatch):
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research(
        price_gbp=24.50, unit="per_m2", source="https://example-merchant.co.uk/mfmdf-9mm",
        quantity_basis="2800x2070 sheet, priced per m2", as_of="2026-09-17"))
    part = _tray()
    out = estimator.estimate_material(part)
    assert "indicative_price" in (out.get("reliability_flags") or [])
    assert out["indicative_price"]["evidence"]["source"].startswith("https://")
    assert any("RESEARCHED indicative price" in str(f)
               for f in part.get("review_flags", []))


def test_the_board_is_asked_for_by_the_square_metre(monkeypatch):
    """A £/sheet figure is worthless without the sheet it was for, and the two travel
    apart. Per m² survives a change of stock size."""
    _no_catalogue(monkeypatch)
    spy = _Research(price_gbp=24.50, unit="per_m2", source="x",
                    quantity_basis="y", as_of="2026-09-17")
    monkeypatch.setattr(estimator, "_rung4_researcher", spy)
    estimator.estimate_material(_tray())
    assert spy.briefs, "the researcher was never asked about the board"
    assert spy.briefs[0]["wanted_unit"] == "square metre"
    assert "9mm" in spy.briefs[0]["description"]
    assert "MFMDF" in spy.briefs[0]["description"]


def test_a_sheet_price_answered_per_each_does_not_price_the_board(monkeypatch):
    """£68 a sheet x 0.1521 "off" = £10.34 — a real price, wrong arithmetic. The unit
    check catches it and the line stays visibly open."""
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research(
        price_gbp=68.0, unit="each", source="https://example-merchant.co.uk/mfmdf-sheet",
        quantity_basis="one 2800x2070 sheet", as_of="2026-09-17"))
    out = estimator.estimate_material(_tray())
    assert out["cost_method"] == "faced_board_unpriced", out.get("cost_method")
    assert out["unit_material_cost_gbp"] is None


def test_research_that_answers_nothing_leaves_the_line_open_and_says_so(monkeypatch):
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research())
    part = _tray()
    out = estimator.estimate_material(part)
    assert out["cost_method"] == "faced_board_unpriced"
    assert any("researched rung could not produce an evidenced figure" in str(f)
               for f in part.get("review_flags", []))


def test_it_never_falls_back_to_the_raw_core(monkeypatch):
    """The rule D-106 restored, and the one this must not quietly undo: plain-MDF money on
    a laminated panel is a 4x under-charge whatever rung produced it."""
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research())
    out = estimator.estimate_material(_tray())
    assert out.get("unit_material_cost_gbp") is None
    assert "kg" not in str(out.get("cost_method"))


def test_a_researched_board_price_still_cannot_come_off_an_estimators_sheet(monkeypatch):
    """The contamination guard is the producer's and is not weakened by reaching it from
    a second caller."""
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research(
        price_gbp=24.50, unit="per_m2", source="x", quantity_basis="y", as_of="2026-09-17",
        origin="estimator_sheet"))
    out = estimator.estimate_material(_tray())
    assert out["cost_method"] == "faced_board_unpriced"


# ── 3 · the date, which never arrived ────────────────────────────────────────────────
#
# The producer requires a source, a date, a unit basis and a quantity basis before a
# researched figure may be used, and refuses the price outright if any is missing. The
# lookup stamps the date on every result it returns, under `price_date`. The adapter
# between them read `as_of`. So the date was present, recorded, correct and dropped in the
# six lines between two modules, and EVERY researched price this engine has ever found was
# refused for want of a date it already had — a whole rung of the ladder inert, with no
# error anywhere to say so.

def test_the_lookups_date_reaches_the_producer(monkeypatch):
    import web_ai_price_lookup as w
    monkeypatch.setattr(w, "lookup_web_ai_price", lambda _s: {
        "found": True, "price_gbp": 24.50, "unit": "per_m2",
        "source_url": "https://example-merchant.co.uk/mfmdf-9mm",
        "price_basis": "2800x2070 sheet", "price_date": "2026-09-17",
        "source_type": "web_search"})
    got = estimator._rung4_researcher({"description": "9mm MFMDF board",
                                       "code": "", "order_quantity": 50,
                                       "wanted_unit": "square metre", "ask": "..."})
    assert got["as_of"] == "2026-09-17", (
        "the lookup's own price_date is dropped — the producer then refuses every "
        "researched figure for want of a date it already had")


def test_a_figure_with_no_date_is_still_refused(monkeypatch):
    """The guard this fault was hiding behind is not weakened by fixing it: a price
    nobody can date cannot be checked, which is what separates it from a typed number."""
    _no_catalogue(monkeypatch)
    monkeypatch.setattr(estimator, "_rung4_researcher", _Research(
        price_gbp=24.50, unit="per_m2", source="https://example.co.uk",
        quantity_basis="per m2"))
    out = estimator.estimate_material(_tray())
    assert out["cost_method"] == "faced_board_unpriced"


# ── 4 · one researcher, not one per caller ───────────────────────────────────────────

def test_the_bought_in_chain_and_the_board_share_one_researcher():
    """Two copies of a price source is how two answers to one question start."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert src.count("def _rung4_researcher(") == 1
    assert src.count("ask=_rung4_researcher") >= 1
    assert "_researcher = _rung4_researcher" in src
