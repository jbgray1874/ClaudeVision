"""A size printed in two units is read by what can be, priced at that reading, still to confirm
(D-445).

8188-08: "KINGDOM: 50mm x 10mm x 2m MAGNET" x14, priced as fourteen two-metre bars (£679 of the
unit) and marked UNRESOLVED (D-432). The pack says which reading is possible: nothing on the
job is longer than about 1,300 mm, so a 2,000 mm bar cannot be and a 2 mm one can. James Gray,
10 Oct: "we need to infer as best we can and also find prices".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                      # noqa: E402
import size_reading as sr                                             # noqa: E402
import wb_populate as wp                                              # noqa: E402
from extractor_patterns import size_mixing_units                      # noqa: E402


def _magnet():
    return {"part_number": "KINGDOM", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14,
            "is_bought_in": True, "page_roles": ["bought_in"]}


def _made(length_mm):
    return {"part_number": "BASE-001", "description": "BASE PLATE", "overall_length_mm": length_mm,
            "overall_width_mm": 200.0, "normalized_material": "MILD STEEL", "pages": [2]}


def test_the_readings_a_two_unit_size_allows_are_as_printed_and_all_in_the_smaller_unit():
    r = sr.readings_of(size_mixing_units("50mm x 10mm x 2m MAGNET"))
    assert [x["label"] for x in r] == ["as printed", "every figure in mm"]
    assert r[0]["figures_mm"] == [50.0, 10.0, 2000.0]
    assert r[1]["text"] == "50mm x 10mm x 2mm" and r[1]["figures_mm"] == [50.0, 10.0, 2.0]


def test_the_yardstick_is_the_stated_envelope_else_the_largest_measured_member():
    y = sr.job_yardstick_mm({}, [_made(1292.0), _magnet()])
    assert (y["mm"], y["basis"]) == (1292.0, "the largest size anything made on the job measures")
    assert y["kg"] is None
    stated = {"llm_full_extract": {"parts": [{"part_number": "GA", "overall_size_mm": "1500 x 600 x 300"}]}}
    y = sr.job_yardstick_mm(stated, [_made(1292.0)])
    assert y["mm"] == 1500.0 and "states" in y["basis"]
    assert sr.job_yardstick_mm({}, [_magnet()])["mm"] is None, "a purchase is no yardstick for itself"


def test_a_reading_heavier_than_the_product_cannot_be_and_the_other_is_inferred():
    """The 8188 shape: the waves are 2.6 m long so length decides nothing; the GA states
    43.6 kg and fourteen 50 x 10 x 2,000 magnet bars weigh 68 kg as ferrite."""
    mag = _magnet()
    summary = {"pages": [{"page_number": "1", "pypdf_text": "HERO HEADER WEIGHT: 43631.32g DRAWING No GA"}]}
    assert sr.apply_size_readings([mag, _made(2608.0)], summary) == 1
    inf = mag["size_reading_inferred"]
    assert inf["text"] == "50mm x 10mm x 2mm"
    assert "68." in inf["why"] and "43.6 kg" in inf["why"] and "magnet" in inf["why"]


def test_a_purchased_line_naming_no_material_is_not_weighed():
    bar = dict(_magnet(), description="50mm x 10mm x 2m BAR")
    summary = {"pages": [{"page_number": "1", "pypdf_text": "WEIGHT: 43631.32g"}]}
    assert sr.apply_size_readings([bar, _made(2608.0)], summary) == 0


def test_a_reading_longer_than_the_job_cannot_be_and_the_other_is_inferred():
    mag = _magnet()
    assert sr.apply_size_readings([mag, _made(1292.0)], {}) == 1
    inf = mag["size_reading_inferred"]
    assert inf["text"] == "50mm x 10mm x 2mm" and inf["printed"] == "50mm x 10mm x 2m"
    assert "2,000 mm" in inf["why"] and "1,292 mm" in inf["why"]
    assert mag["price_chain_description"] == "50mm x 10mm x 2mm MAGNET"
    assert mag["description"] == "50mm x 10mm x 2m MAGNET", "the printed words stay on the record"


def test_where_both_readings_fit_nothing_is_inferred():
    mag = _magnet()
    assert sr.apply_size_readings([mag, _made(2500.0)], {}) == 0
    assert "size_reading_inferred" not in mag and "price_chain_description" not in mag


def test_where_the_job_measures_nothing_nothing_is_inferred():
    mag = _magnet()
    assert sr.apply_size_readings([mag], {}) == 0
    assert "size_reading_inferred" not in mag


def test_a_line_with_one_unit_is_left_alone():
    tape = {"part_number": "PSA1999C", "description": "25mm D/S ADHESIVE SUPERTAPE, L: 480mm",
            "is_bought_in": True, "page_roles": ["bought_in"]}
    assert sr.apply_size_readings([tape, _made(1292.0)], {}) == 0


def test_the_price_chain_is_asked_the_inferred_reading(monkeypatch):
    asked = {}

    def _resolve(part):
        asked["description"] = part.get("price_chain_description") or part.get("description")
        return {"result": {"selected": {"source": "web", "price": 0.9}},
                "applied_unit_cost": 0.9, "matched_part_code": "KINGDOM"}
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _resolve)
    mag = _magnet()
    sr.apply_size_readings([mag, _made(1292.0)], {})
    pe = estimator.estimate_part(mag, 1)
    assert asked["description"] == "50mm x 10mm x 2mm MAGNET"
    assert pe["material_estimate"]["unit_material_cost_gbp"] == 0.9


def test_the_resolver_itself_reads_the_inferred_description():
    """_resolve_part_system_cost asks the chain with price_chain_description, not the print."""
    import inspect
    src = inspect.getsource(estimator._resolve_part_system_cost)
    assert 'part.get("price_chain_description")' in src


def test_the_mark_the_line_and_the_question_say_what_was_read_and_still_block():
    mag = _magnet()
    sr.apply_size_readings([mag, _made(1292.0)], {})
    pe = estimator.estimate_part(mag, 1)
    mark = pe["_price_unresolved"]
    assert mark["inferred_text"] == "50mm x 10mm x 2mm" and "read as 50mm x 10mm x 2mm" in mark["reason"]
    note = wp.unresolved_reading_note(pe)
    assert "read as 50mm x 10mm x 2mm" in note and "blocked until confirmed" in note
    qs = [q for q in pe.get("manufacturing_questions") or [] if "mixes m and mm" in q["issue"]]
    assert qs and "read as 50mm x 10mm x 2mm" in qs[0]["assumption"] and "blocked" in qs[0]["assumption"]
    import invariants
    v = invariants.check_an_unresolved_reading_blocks_the_quote(
        {"estimate_summary": {"part_estimates": [dict(pe, material_estimate={"unit_material_cost_gbp": 0.9})]}})
    assert v and v[0]["severity"] == invariants.BLOCKING, "inferred is not confirmed: the quote still waits"


def test_without_an_inference_the_note_reads_as_d432_wrote_it():
    assert wp.unresolved_reading_note({"_price_unresolved": {"units": ["m", "mm"]}}) == \
        "UNRESOLVED READING (m and mm in one size): priced as printed, a working figure — customer quote blocked until confirmed"


def test_a_flexible_or_bonded_magnetic_product_is_not_weighed_as_a_sintered_magnet():
    """Ferrite is the lightest common SINTERED grade; flexible and bonded magnetic products are
    lighter still and are weighed as none of these — the pack's weight then decides nothing."""
    tape = dict(_magnet(), description="50mm x 10mm x 2m FLEXIBLE MAGNETIC TAPE")
    summary = {"pages": [{"page_number": "1", "pypdf_text": "WEIGHT: 43631.32g"}]}
    assert sr.density_for_purchased(tape["description"]) is None
    assert sr.apply_size_readings([tape, _made(2608.0)], summary) == 0


def test_the_inference_says_it_is_inferred_and_what_it_rests_on():
    mag = _magnet()
    summary = {"pages": [{"page_number": "1", "pypdf_text": "WEIGHT: 43631.32g"}]}
    sr.apply_size_readings([mag, _made(2608.0)], summary)
    flag = " ".join(str(f) for f in mag["review_flags"])
    assert "inferred, not confirmed" in flag and "density" in flag


def test_a_late_record_is_read_before_it_is_costed(monkeypatch):
    """The 10:12 book: KINGDOM is a row only the table reader saw, appended after costing, so
    the resolver that ran before costing never met it. The late pass reads it too."""
    asked = {}

    def _resolve(part):
        asked["description"] = part.get("price_chain_description") or part.get("description")
        return {"result": {"selected": {"source": "web", "price": 0.9}},
                "applied_unit_cost": 0.9, "matched_part_code": "KINGDOM"}
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _resolve)
    made = dict(_made(2608.0), cost_breakdown={"total": 1.0})      # already costed
    late = _magnet()
    summary = {"estimate_summary": {"part_estimates": [made, late]},
               "pages": [{"page_number": "1", "pypdf_text": "WEIGHT: 43631.32g"}]}
    assert estimator.cost_uncosted_bought_in_records(summary) == 1
    pe = summary["estimate_summary"]["part_estimates"][1]
    assert asked["description"] == "50mm x 10mm x 2mm MAGNET"
    assert pe["_price_unresolved"]["inferred_text"] == "50mm x 10mm x 2mm"
    assert pe["material_estimate"]["unit_material_cost_gbp"] == 0.9
