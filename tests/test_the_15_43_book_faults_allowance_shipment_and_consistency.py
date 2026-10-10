"""The 15:43 live book (f4b1a7b) carried D-454 and still failed two money gates — each a rule
(D-455).

1. 013 stayed at £2.34 on 2190 x 17: the pre-costing pass read the uncosted page dimensions,
   found no measured outlines to vote with, and stood down — while the costed record carried
   five measured outlines that weigh as mild steel, and the report said so. The reading the
   report states and the reading the money uses must be one, so a SECOND PASS runs after
   costing, over exactly what the weight check reads, and re-costs the unmeasured blank on
   its allowance.
2. Packaging £10.00 / £10.06 stood as weak history: offline it is right that nothing else
   answered, but the researcher's unit answer ("per_pallet", "Per Pallet", "pallets") was
   compared as a raw string to "pallet" and refused on spelling. The unit is normalised; a
   refusal is recorded and said on the line's basis.
3. The report contradicted the sheet four ways: 011's own measured flat called a provisional
   model extent beside a stale 30 x 6 page read; the GA asked "3 or 10 mm?" though an assembly
   prices no gauge; the insert's past-SDI-quote price filed as "researched market price"; the
   Quantity Breaks note said packaging falls by spreading an order figure beside rows reading
   £20.06 a unit at every quantity. And the goalpost's cut list (2 x 300 + 1 x 1,272) carried
   no cutting labour: a cut list IS cuts, so the saw is charged per piece.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as cl                                         # noqa: E402
import costed_facts as cf                                             # noqa: E402
import estimator as e                                                 # noqa: E402
import source_precedence as sp                                        # noqa: E402


def _measured_acrylic(pn, L, W, area, kg):
    """A costed part as the live record holds it: a measured DXF outline, a stale page read."""
    return {"part_number": pn, "description": "WAVE", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 3.0, "quantity": 1, "stated_weight_kg": kg,
            "geometry_source": "dxf_flat_pattern", "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": L, "blank_width_mm": W,
                                    "blank_area_mm2": area}}


def _unmeasured_013():
    return {"part_number": "013", "description": "WAVE LAYER 3", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 3.0, "quantity": 1, "stated_weight_kg": 11.731,
            "geometry_source": "dxf_cut_length_only",
            "normalized_geometry": {"blank_length_mm": 2190.34, "blank_width_mm": 17.0}}


# ── 1. the second pass reaches the money ─────────────────────────────────────────────

def test_the_costed_records_own_outlines_fill_an_unmeasured_blank_after_costing():
    parts = [_measured_acrylic("014", 2257.4, 199.99, 285684, 6.728),
             _measured_acrylic("015", 2354.72, 99.99, 106666, 2.512),
             _measured_acrylic("008", 1143, 98, 111517, 2.626), _unmeasured_013()]
    pes = [e.estimate_part(p, 1) for p in parts]
    before = pes[3]["material_estimate"]["unit_material_cost_gbp"]
    assert pes[3]["material_estimate"]["blank_width_mm"] == 17.0
    assert e.fill_unmeasured_blanks_from_the_job(parts, pes, 1) == ["013"]
    me = pes[3]["material_estimate"]
    assert me["blank_length_mm"] == 2190.34 and abs(me["blank_width_mm"] - 227.4) < 0.5
    assert me["unit_material_cost_gbp"] > before * 4
    flags = " ".join(str(f) for f in parts[3]["review_flags"])
    assert "MATERIAL-AREA ALLOWANCE" in flags
    assert not any(str(f).startswith("WEIGHT CHECK") for f in parts[3]["review_flags"]), \
        "the stale 'priced on 2190 x 17 until then' reading goes with the stale price"
    issues = [str(q.get("issue")) for q in parts[3]["manufacturing_questions"]]
    assert any(i.startswith("Blank of 013: not measured — material priced as an area allowance")
               for i in issues)
    assert not any("the recorded blank was not measured and does not weigh" in i for i in issues)


def test_one_measured_part_is_no_pack_reading_and_a_measured_outline_is_left_alone():
    parts = [_measured_acrylic("014", 2257.4, 199.99, 285684, 6.728), _unmeasured_013()]
    pes = [e.estimate_part(p, 1) for p in parts]
    assert e.fill_unmeasured_blanks_from_the_job(parts, pes, 1) == []
    parts2 = [_measured_acrylic("014", 2257.4, 199.99, 285684, 6.728),
              _measured_acrylic("015", 2354.72, 99.99, 106666, 2.512),
              _measured_acrylic("011", 745.16, 157.11, 117027, 9.187)]
    pes2 = [e.estimate_part(p, 1) for p in parts2]
    assert e.fill_unmeasured_blanks_from_the_job(parts2, pes2, 1) == [], \
        "011's flat measured 117,027 mm² — a measured outline is never re-costed on a weight"


def test_a_part_with_a_measured_outline_never_takes_a_provisional_blank():
    p = _measured_acrylic("011", 30.0, 6.0, 117027, 9.187)       # stale page read beside a flat
    assert e._apply_mass_implied_blank(p) is None and "_blank_provisional" not in p


def test_the_second_pass_runs_in_estimate_document():
    import inspect
    assert "fill_unmeasured_blanks_from_the_job" in inspect.getsource(e.estimate_document)


# ── 2. the researched unit, as the model writes it ───────────────────────────────────

def test_the_units_spellings_are_one_unit():
    for said in ("per_pallet", "Per Pallet", "pallets", "PER-PALLET", "GBP per pallet"):
        assert cl._unit_word(said) == "pallet", said
    assert cl._unit_word("per order") == "order" and cl._unit_word("each") == "each"


def test_a_refused_or_absent_answer_is_said_on_the_basis(monkeypatch):
    import palletising
    monkeypatch.setattr(palletising, "plan_shipment", lambda parts, q: {"pallet_count": 2.0})
    monkeypatch.setattr(cl, "_commercial_researcher",
                        lambda brief: {"price_gbp": 120.0, "unit": "per order"})
    order = {"order_quantity": 5, "shipment": {"pallet_count": 2.0},
             "shippable_parts": [{"part_number": "P"}]}
    assert cl._counted_shipment_price("DELIVERY", order) is None
    why = cl.shipment_status("DELIVERY", order)
    assert "per order" in why and "not per pallet" in why
    monkeypatch.setattr(cl, "_commercial_researcher",
                        lambda brief: {"price_gbp": 60.0, "unit": "Per Pallet"})
    got = cl._counted_shipment_price("DELIVERY", order)
    assert got and got["order_gbp"] == 120.0, "the model's spelling of the unit is accepted"


def test_weak_history_names_why_the_shipment_did_not_price(monkeypatch):
    monkeypatch.setattr(cl, "_sdi_live_rate", lambda code, order: {
        "order_gbp": 50.0, "source_class": "sdi_history", "source_name": "SDI Live history",
        "comparability": "same customer, quantity not held on the history header",
        "working": "median GBP 10.00 a unit"})
    monkeypatch.setattr(cl, "_counted_shipment_price", lambda code, order: None)
    cl._SHIPMENT_STATUS["PACKAGING|5"] = "the market answered per order, not per pallet — refused"
    ch = cl._choose_commercial_basis("PACKAGING", {"order_quantity": 5, "customer": "M&S"})
    assert "weak comparability" in ch["basis"] and "refused" in ch["basis"], ch["basis"]


# ── 3. the report and the sheet agree ────────────────────────────────────────────────

def test_an_assembly_is_asked_no_gauge_question():
    ga = {"part_number": "8188-08_GA", "description": "ASSY",
          "normalized_thickness_mm": 3.0}
    sp.apply_field(ga, "normalized_thickness_mm", 3.0, "drawing_deterministic")
    sp.apply_field(ga, "normalized_thickness_mm", 10.0, "drawing_deterministic")
    assert not any("one reader, two readings" in str(f) for f in ga.get("review_flags") or []), \
        "a gauge on an assembly prices nothing, so two readings of it are not a decision"
    part = {"part_number": "P-01", "normalized_thickness_mm": 3.0}
    sp.apply_field(part, "normalized_thickness_mm", 3.0, "drawing_deterministic")
    sp.apply_field(part, "normalized_thickness_mm", 10.0, "drawing_deterministic")
    assert any("one reader, two readings" in str(f) for f in part.get("review_flags") or []), \
        "a cut part keeps the question"


def test_a_past_sdi_quotes_line_is_classed_as_sdi_history_not_market():
    origin = cf._price_origin(
        {"part_number": "FIXING M6X12MM", "supplier": "historical_quote_material_line",
         "material_estimate": {"cost_method": "historical_quote_material_line"}},
        "bought_in", None, 0.10, 0.10, None, False, row_text="")
    assert origin["class"] == "sdi_history_line"
    assert "past SDI quote" in origin["label"] and "market" not in origin["label"].lower()


def test_a_derived_wire_length_removes_the_no_length_note():
    import wire_sheet_reader as wsr
    part = {"part_number": "8188-08-004", "description": "WIRE WORK MESH FRAME",
            "normalized_material": "MILD STEEL WIRE", "pages": ["3"], "wire_gauge_mm": 6.0,
            "review_flags": ["8188-08-004 is round stock and its LENGTH is not known — it is "
                             "priced per metre, so the length is the money. ..."]}
    summary = {"pages": [{"page_number": "3",
                          "pypdf_text": "6 WIRE WORK FRAME 1081 EXT. X 206 EXT."}]}
    assert wsr.apply_wire_callouts_to_parts([part], summary["pages"]) == 1
    assert part["wire_length_derived_mm"] == 2574.0
    assert not any("LENGTH is not known" in str(f) for f in part["review_flags"]), \
        "the note that said no length was derived is untrue once one is"


def test_the_quantity_breaks_note_reads_its_own_rows():
    import openpyxl
    from quantity_breaks_tab import _write_basis
    from openpyxl.styles import Font, Alignment
    rows = [{"quantity": 1, "unit": 100.0, "material": 40.0, "labour": 60.0,
             "order_charges_per_unit": 20.06, "setup_per_unit": 30.0},
            {"quantity": 50, "unit": 70.0, "material": 40.0, "labour": 30.0,
             "order_charges_per_unit": 20.06, "setup_per_unit": 0.6}]
    wb = openpyxl.Workbook()
    ws = wb.active
    _write_basis(ws, rows, 1, Font(bold=True), Alignment)
    blob = " ".join(str(c.value) for r in ws.iter_rows() for c in r if c.value)
    assert "carried at £20.06 a unit at every quantity" in blob
    assert "do not fall with the order" in blob
    assert "priced for the whole order and divided" not in blob


# ── the goalpost's cut list is cut ───────────────────────────────────────────────────

def test_a_sections_own_cut_list_is_sawn_per_piece():
    goal = {"part_number": "8188-29-001", "description": "COMMON HEADER GOALPOST",
            "normalized_material": "MILD STEEL", "quantity": 1, "textual_operations": ["welding"],
            "section_stock": {"a": 25.4, "b": 25.4, "wall_mm": 1.22,
                              "cut_lengths_mm": [300.0, 300.0, 1272.0],
                              "cut_lengths_mm_source": "drawing_deterministic"}}
    pr = e.estimate_process_times(goal, quantity=1)
    assert pr["run_times_min_per_unit"]["saw"] == 4.5, "three cuts at 90 s each"
    assert pr["setup_times_min"]["saw"] == 10.0
    assert any("sawn to its own cut list (3 piece(s)" in str(f) for f in goal["review_flags"])
    no_list = {"part_number": "T-1", "description": "TUBE", "normalized_material": "MILD STEEL",
               "quantity": 1, "section_stock": {"a": 25.0, "b": 25.0, "length_mm": 900.0}}
    pr2 = e.estimate_process_times(no_list, quantity=1)
    assert "saw" not in (pr2.get("run_times_min_per_unit") or {}), \
        "no cut list stated, no saw invented"


# ── the first replay's stand-down (D-456) ────────────────────────────────────────────

def _live_shape(pn, L, W, area, kg):
    """As the saved record holds a wave: measured DXF net area, size stamped INFERRED (read
    off a shared sheet) — exactly what refused the vote on the first replay."""
    p = _measured_acrylic(pn, L, W, area, kg)
    p["blank_is_inferred"] = True
    p["geometry_source"] = "dxf_cut_length_only"
    del p["dxf_augmented"]
    return p


def test_inferred_sizes_with_measured_areas_still_vote_and_fill_the_gap():
    parts = [_live_shape("014", 2257.4, 199.99, 285684, 6.728),
             _live_shape("015", 2354.72, 99.99, 106666, 2.512),
             _live_shape("008", 1143, 98, 111517, 2.626), _unmeasured_013()]
    pes = [e.estimate_part(p, 1) for p in parts]
    assert e.fill_unmeasured_blanks_from_the_job(parts, pes, 1) == ["013"]
    me = pes[3]["material_estimate"]
    assert abs(me["blank_width_mm"] - 227.4) < 0.5 and me["unit_material_cost_gbp"] > 5.0
    assert parts[3]["_blank_provisional"]["basis"] == "mass_implied_area"


def test_a_blank_this_rule_wrote_cannot_vote_and_a_stand_down_is_said(capsys):
    allowed = _live_shape("099", 2190.0, 227.0, 497000, 11.7)
    allowed["_blank_provisional"] = {"basis": "mass_implied_area"}
    assert e._weight_check_reading(allowed) is None, "feeding the allowance back is circular"
    parts = [_live_shape("014", 2257.4, 199.99, 285684, 6.728), _unmeasured_013()]
    pes = [e.estimate_part(p, 1) for p in parts]
    assert e.fill_unmeasured_blanks_from_the_job(parts, pes, 1) == []
    out = capsys.readouterr().out
    assert "no model-material reading" in out and "013" in out, \
        "one vote is no pack reading, and the stand-down is said, not silent"


def test_a_cut_path_only_dxf_is_not_a_measured_blank_on_the_gate():
    from check_book_against_brief import check
    summary = {"manufacturing_writeup": {"parts": [
                   {"part_number": "013", "geometry_source": "dxf_cut_length_only"}]},
               "estimate_summary": {"part_estimates": [
                   {"part_number": "013", "material_estimate": {"unit_material_cost_gbp": 1.54}}]}}
    res = check(summary, {"provisional_material": {"013": {"min_unit_material_gbp": 5}}})
    (name, item, ok, detail), = [r for r in res.rows if r[0] == "provisional_material"]
    assert not ok and "measured outline" not in detail and "no provisional record" in detail


def test_weak_history_passes_only_with_the_shipments_refusal_stated():
    from check_book_against_brief import check

    def _summary(basis):
        return {"manufacturing_writeup": {"parts": []}, "estimate_summary": {"part_estimates": []},
                "commercial_lines": [{"code": "PACKAGING", "basis_chosen": basis,
                                      "order_gbp_at_breaks": {1: 10.0, 50: 500.0}}]}
    facts = {"commercial_basis": ["PACKAGING"], "commercial_breaks": [1, 50]}
    said = ("SDI Live history only — weak comparability; the counted shipment could not be "
            "priced (the market answered per order, not per pallet — refused)")
    unsaid = "SDI Live history only — weak comparability, no shipment could be priced"
    lost = ("SDI Live history only — weak comparability; the counted shipment could not be "
            "priced (the shipment rung recorded no reason — investigate)")
    for basis, want in ((said, True), (unsaid, False), (lost, False)):
        res = check(_summary(basis), facts)
        (_, _, ok, _), = [r for r in res.rows if r[0] == "commercial_basis"]
        assert ok is want, basis


def test_every_shipment_refusal_carries_a_reason(monkeypatch):
    import palletising
    monkeypatch.setattr(palletising, "plan_shipment", lambda parts, q: {"pallet_count": 2.0})
    monkeypatch.setattr(cl, "_commercial_researcher", lambda brief: {})
    order = {"order_quantity": 7, "shipment": {"pallet_count": 2.0},
             "shippable_parts": [{"part_number": "P"}]}
    assert cl._counted_shipment_price("PACKAGING", order) is None
    assert cl.shipment_status("PACKAGING", order), "a silent refusal is how weak history won unexplained"
