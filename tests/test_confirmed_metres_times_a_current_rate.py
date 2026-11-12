r"""Edging is two facts. The engine had a rule for neither, and refused the whole line.

James Gray, 17 September 2026:

    "I don't understand why we can't price edging... confirmed banded metres x current
     GBP/metre. we can get a current GBP/metre from an LLM or from SDI Live and what does
     confirmed banded metres mean? The length?... so, we should be able to price in this
     case."

He is right, and the answer is yes. The line is:

    EDGING = CONFIRMED BANDED METRES  x  CURRENT GBP PER METRE

and the two halves have different owners. The METRES are the product's design - which
edges are exposed - and only the drawing or a person who has read it can say. The RATE is
a purchase, and SDI Live, the supplier catalogue, a quote or evidenced research can all
answer it. Neither half may be inferred from the other, and the perimeter is not a
stand-in for either.

WHAT WAS ACTUALLY MISSING ON 11908-21. The DXFs carry no layer data and no note names an
edge, so nothing measurable could answer - and Tony had already said 5.0 m a tray. That is
a stated physical extent of the product, the same class of fact as "the tube bend is not
required", and there was nowhere to put it. So the answers file takes it.

AND THE UNIT THE RATE COMES BACK IN IS NOT A DETAIL. The producer multiplies the figure by
the line's quantity, and the quantity here is METRES. A researcher asked for the price of
"one ABS edging" prices a REEL - correctly sourced, correctly dated, perfectly good
evidence - and five metres of tray then carries a hundred metres of tape. Every field in
the evidence block is true and only the unit disagrees, so the unit is checked, and a
disagreement is REFUSED rather than converted: dividing a reel price by a reel length
nobody stated would be inventing the quantity this engine is not allowed to invent.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import indicative_price as ip  # noqa: E402
from edge_banding import banded_length_mm  # noqa: E402

_TRAY = {"part_number": "11908-21-01J", "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2}


# ── 1 · the metres: a person may state them, and they outrank the geometry ───────────

def test_a_confirmed_extent_answers_where_the_drawing_does_not():
    """11908-21 exactly: no edging layer, no note, and an estimator who knows the tray."""
    out = banded_length_mm(dict(_TRAY, _confirmed_banded_mm=5000.0,
                                _confirmed_banded_by="Tony Ford"))
    assert out["mm"] == 5000.0
    assert out["basis"] == "estimator_confirmed"
    assert "Tony Ford" in out["evidence"]


def test_it_outranks_a_measurement():
    """A layer is the drawing office's reading of the design; a confirmation is a person
    saying what the product is. Where they disagree the person is asked, not overruled."""
    out = banded_length_mm(dict(_TRAY, _confirmed_banded_mm=5000.0,
                                normalized_geometry={"length_mm_by_layer":
                                                     {"EDGEBAND": 780.0}}))
    assert out["mm"] == 5000.0, "a measured layer overrode a person's confirmation"


def test_zero_is_an_answer_and_not_a_confirmation():
    """"This part is not banded" is said by leaving it out or by the absence of evidence —
    a zero must not read as a confirmed length of nothing and hide the real state."""
    out = banded_length_mm(dict(_TRAY, _confirmed_banded_mm=0.0))
    assert out["mm"] is None
    assert out["basis"] == "no_evidence"


def test_nothing_confirmed_behaves_exactly_as_before():
    out = banded_length_mm(dict(_TRAY))
    assert out["mm"] is None and out["basis"] == "no_evidence"
    assert out["drawn_perimeter_mm"] == 1560.0


# ── 2 · the answers file carries it, in either form estimators state it ──────────────

def _decisions(block):
    import estimator_confirmed as ec
    return ec._read_decisions({"estimator_decisions": block}, "test.json")


def test_metres_a_finished_unit():
    """Tony's own form: 5.0 m a tray, across every component in it."""
    out, problems = _decisions({"banded_metres": 5.0})
    assert out["banded_metres"] == {"per_unit": 5.0}
    assert problems == []


def test_metres_per_named_part():
    out, problems = _decisions({"banded_metres": {"11908-21-01J": 1.56,
                                                  "11908-21-02J": 0.8}})
    assert out["banded_metres"] == {"per_part": {"11908-21-01J": 1.56,
                                                 "11908-21-02J": 0.8}}
    assert problems == []


def test_either_spelling_carries_the_same_ruling():
    """`banded_length_m` is the name it was asked for in and reads plainest on a
    hand-typed file. Accepting only the other one would make a correctly-stated ruling do
    nothing, silently."""
    a, _ = _decisions({"banded_length_m": 5.0})
    b, _ = _decisions({"banded_metres": 5.0})
    assert a == b == {"banded_metres": {"per_unit": 5.0}}


def test_tonys_own_ruling_parses_clean_out_of_config():
    """The ruling the run will actually read — in config.JOB_DECISIONS, arriving with a
    pull, not a shape written here to pass."""
    import json
    import config
    import estimator_confirmed as ec
    got, problems = ec.decisions_from_config("11908-21")
    out = got["estimator_decisions"]
    assert out["banded_metres"] == {"per_unit": 5.0}
    assert out["commercial_excluded"] == ["DELIVERY"]
    assert problems == []
    # AND NO PRICE IN IT. His own historic per-metre figure is his; the metres are a
    # measurement of the product and the rate is a purchase.
    assert "0.35" not in json.dumps(config.JOB_DECISIONS["11908-21"])


def test_a_negative_length_is_refused_and_named():
    out, problems = _decisions({"banded_metres": -5.0})
    assert "banded_metres" not in out
    assert any("negative" in p for p in problems)


def test_a_word_where_a_length_belongs_is_refused_and_named():
    out, problems = _decisions({"banded_metres": "about five"})
    assert "banded_metres" not in out
    assert any("metres per finished unit" in p for p in problems)


def test_a_comment_beside_the_ruling_is_not_reported_as_one():
    _, problems = _decisions({"_why_banded_metres": "Tony, 17 Sep: 5m a tray",
                              "banded_metres": 5.0})
    assert problems == []


# ── 3 · the rate: asked for in the unit the line is bought by ────────────────────────

_EDGING = {"code": "EDGE23X1ABS", "description": "ABS edging 23 x 1mm",
           "quantity": 5.0, "unit_of_measure": "m"}


def test_the_brief_asks_per_metre_for_a_line_bought_by_the_metre():
    brief = ip.research_brief(_EDGING, order_qty=50)
    assert brief["wanted_unit"] == "metre"
    assert "PER METRE" in brief["ask"]
    assert "reel" in brief["ask"], "nothing warned against pricing a whole reel"


def test_an_each_line_is_asked_for_exactly_as_it_always_was():
    brief = ip.research_brief({"code": "FIXING1270", "description": "Bumpon EZ103",
                               "quantity": 4}, order_qty=50)
    assert brief["wanted_unit"] == "each"
    assert "PER EACH" in brief["ask"]
    assert "reel" not in brief["ask"]


def test_a_metre_rate_prices_the_line():
    """The whole of James's question, in one assertion: 5 m x £1.85 = £9.25 a unit."""
    got = ip.resolve_indicative(
        _EDGING, order_qty=50, as_of="2026-09-17",
        ask=lambda _b: {"price_gbp": 1.85, "unit": "per_metre",
                        "source": "https://example-supplier.co.uk/abs-edging-23x1",
                        "quantity_basis": "100 m reel, priced per metre"})
    assert got["price_gbp"] == 9.25, got
    assert got["evidence"]["unit_basis"] == "per_metre"
    assert "metre" in got["calculation"]["working"]
    assert got["status"] == ip.LLM_INDICATIVE_STATUS


def test_a_reel_price_answered_per_each_is_refused_not_multiplied():
    """£210 for a reel x 5 "off" = £1,050 of tape on a tray. Every evidence field is
    present and true; only the unit disagrees, so only the unit can catch it."""
    got = ip.resolve_indicative(
        _EDGING, order_qty=50, as_of="2026-09-17",
        ask=lambda _b: {"price_gbp": 210.0, "unit": "each",
                        "source": "https://example-supplier.co.uk/abs-edging-reel",
                        "quantity_basis": "one 100 m reel"})
    assert got["price_gbp"] is None
    assert "bought by the metre" in got["missing"]
    assert "per each" in got["missing"]


def test_the_refusal_does_not_convert_the_reel_itself():
    """Dividing £210 by a reel length nobody stated is the engine inventing the quantity
    it exists to refuse to invent."""
    got = ip.resolve_indicative(
        _EDGING, order_qty=50, as_of="2026-09-17",
        ask=lambda _b: {"price_gbp": 210.0, "unit": "each", "source": "x",
                        "quantity_basis": "one 100 m reel"})
    assert got["price_gbp"] is None
    assert "2.1" not in str(got.get("price_gbp"))


def test_an_each_line_is_not_subjected_to_the_unit_check():
    """The control. Nothing that priced before may stop pricing because of this rule."""
    got = ip.resolve_indicative(
        {"code": "FIXING1270", "description": "Bumpon EZ103", "quantity": 4},
        order_qty=50, as_of="2026-09-17",
        ask=lambda _b: {"price_gbp": 0.11, "unit": "each", "source": "https://rs.example",
                        "quantity_basis": "pack of 120"})
    assert got["price_gbp"] == 0.44, got


def test_a_metre_line_still_cannot_be_priced_off_an_estimators_sheet():
    """The contamination guard is not weakened by any of this."""
    got = ip.resolve_indicative(
        dict(_EDGING, input_origins={"description": "estimator_sheet"}),
        order_qty=50, as_of="2026-09-17",
        ask=lambda _b: {"price_gbp": 1.85, "unit": "per_metre", "source": "x",
                        "quantity_basis": "y"})
    assert got["price_gbp"] is None
    assert "estimator_sheet" in got["missing"]


# ── 4 · and the researcher is told which unit to answer in ───────────────────────────

def test_the_lookup_spec_carries_the_unit_it_must_price_in():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert '"wanted_unit": _brief.get("wanted_unit")' in src
    assert '"unit_of_measure": part.get("unit_of_measure")' in src, (
        "the line's own unit never reaches the brief — recorded under one name, read "
        "under another")


def test_a_per_unit_confirmation_replaces_the_sum_rather_than_joining_it():
    """Tony's 5 m is the banded edge across every component of one tray. Adding it to what
    the parts measured would count the same metres twice."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    start = src.index("# ── ABS EDGING: A MATERIAL LINE, NOT A QUESTION ─")
    block = src[start:start + 5200]
    assert '_edge_m = round(float(_bm_unit), 3)' in block
    assert '_p["_confirmed_banded_mm"] = float(_bm_per_part[_pn_e]) * 1000.0' in block
    for banned in ("unit_cost_gbp", "unit_material_cost_gbp", "price_gbp"):
        assert banned not in block, (
            f"the edging mint sets {banned} — the rate belongs to the pricing chain")


def test_the_prompt_says_how_the_line_is_bought():
    from web_ai_price_lookup import _build_spec_block
    block = _build_spec_block(description="ABS edging 23 x 1mm", wanted_unit="metre")
    assert "PER METRE" in block
    assert "reel" in block
    plain = _build_spec_block(description="Bumpon EZ103", wanted_unit="each")
    assert "PER" not in plain, "an each line gained a unit instruction it does not need"
