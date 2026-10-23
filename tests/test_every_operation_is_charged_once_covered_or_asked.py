"""D-589: the rules the 0351292 09:48 book broke, held as generic rules with broken cases beside
the passing ones.

    Every required operation is charged once, covered by a named charge, or explicitly asked.
    A blank is read from the part's own sheet, and its own sheet's weight confirms it.
    A formed shape is folded from sheet unless a section is named; a radius its flat cannot
    hold is rolled.
    Coating and material follow the assembly's actual members.
    Reporting says which lines are charged, excluded, provisional or not verified.

The sheets are drawn here with PyMuPDF in the shapes the real packs print (a rotated upright
figure, a decimal comma, a revision table where the template expects one or where it does not),
so the readers are exercised on PDFs, not on dictionaries that say what a PDF would have said.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("SDI_OFFLINE", "1")

fitz = pytest.importorskip("fitz", reason="the sheet readers read PDFs")

import costed_facts as cf  # noqa: E402
import detail_page_geometry as g  # noqa: E402
import estimator as e  # noqa: E402
import formed_shape as fs  # noqa: E402
import route_compiler as rc  # noqa: E402
import source_precedence as sp  # noqa: E402
import wb_populate as W  # noqa: E402


def _sheet(tmp_path, name, items, *, weight=None, number=1, dn=None):
    """One A3 sheet with `items` = [(text, x, y, rotate)], and the page record a scan makes."""
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)
    for text, x, y, rot in items:
        page.insert_text((x, y), text, fontsize=9, rotate=rot)
    path = tmp_path / f"{name}.pdf"
    doc.save(str(path))
    doc.close()
    return {"page_number": number, "page": number, "source_pdf_path": str(path),
            "text": "\n".join(t for t, *_ in items),
            "page_analysis": {"title_block": {"weights": [weight] if weight else [],
                                              "drawing_numbers": [dn] if dn else []}}}


def _sheet_part(pn, desc, t, **kw):
    p = {"part_number": pn, "description": desc, "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": t, "quantity": 1}
    p.update(kw)
    return p


# ── a small blank stands on its own sheet's weight, never on figures alone ────────────────

def _top_blank_sheet(tmp_path, weight="0.003KG"):
    return _sheet(tmp_path, "top", [("30", 500, 300, 0), ("7,4", 420, 340, 90), ("R2", 300, 300, 0)],
                  weight=weight)


def test_a_small_blank_with_a_decimal_is_read_and_its_weight_confirms_it(tmp_path):
    part = _sheet_part("T-1", "TOP BLANK", 2.0, weights=["8.1KG", "0.003KG"])
    blank = g.provisional_blank_from_sheets(part, [_top_blank_sheet(tmp_path)])
    assert blank and (blank["length"], blank["width"]) == (30.0, 7.4)
    assert blank["weight_confirmed_small_part"] is True
    assert "0.003 kg" in blank["working"], "the weight it agrees with is its own sheet's"


def test_the_same_small_blank_without_a_weight_is_refused(tmp_path):
    part = _sheet_part("T-1", "TOP BLANK", 2.0)
    assert g.provisional_blank_from_sheets(part, [_top_blank_sheet(tmp_path, weight=None)]) is None
    assert "below the smallest size" in part["_provisional_blank_refused"]


def test_a_feature_callout_is_not_made_a_part_by_a_weight_it_does_not_match(tmp_path):
    """12392's 16 x 3.7 callout: a small figure pair on a sheet whose weight is a real part's."""
    sheet = _sheet(tmp_path, "callout", [("16", 500, 300, 0), ("3,7", 420, 340, 90)],
                   weight="1.2KG")
    assert g.provisional_blank_from_sheets(_sheet_part("C-1", "BRACKET", 2.0), [sheet]) is None


def _small_blank_part(confirmed):
    part = _sheet_part("T-1", "TOP BLANK", 2.0,
                       _blank_provisional={"weight_confirmed_small_part": confirmed})
    g._write_blank(part, 30.0, 7.4, g.PROVISIONAL_SOURCE)
    return part


def test_the_costing_floor_keeps_a_small_blank_its_weight_confirmed():
    assert e._blank_that_could_have_been_cut(_small_blank_part(True), 30.0, 7.4) == (30.0, 7.4)


def test_the_costing_floor_refuses_the_same_blank_unconfirmed():
    assert e._blank_that_could_have_been_cut(_small_blank_part(False), 30.0, 7.4) != (30.0, 7.4)


# ── the flat's width is the figure the weight agrees with; a revision zone is read for what it holds

def _downstand_items(rev_word=False):
    items = [("1435,2", 512, 605, 0), ("208,9", 853, 410, 90), ("25", 1106, 517, 90),
             ("703", 600, 200, 0), ("R225", 30, 335, 0), ("FLAT PATTERN", 300, 450, 0)]
    if rev_word:
        items.append(("REV", 1000, 480, 0))
    return items


def test_a_dimension_in_an_empty_revision_zone_is_read(tmp_path):
    figs = g.read_sheet_figures(_sheet(tmp_path, "d1", _downstand_items()))["figures"]
    assert (25.0, "v") in figs


def test_a_revision_table_where_the_template_expects_one_is_still_skipped(tmp_path):
    figs = g.read_sheet_figures(_sheet(tmp_path, "d2", _downstand_items(rev_word=True)))["figures"]
    assert (25.0, "v") not in figs


def test_a_flat_pattern_too_heavy_for_its_weight_takes_the_width_the_weight_agrees_with(tmp_path):
    part = _sheet_part("D-1", "DOWNSTAND", 2.0)
    blank = g.provisional_blank_from_sheets(
        part, [_sheet(tmp_path, "d3", _downstand_items(), weight="0.6KG")])
    assert blank and (blank["length"], blank["width"]) == (1435.2, 25.0)
    assert "confirm the flat width" in blank["working"]


def test_two_widths_the_weight_fits_equally_decide_nothing(tmp_path):
    items = _downstand_items() + [("26", 700, 300, 90)]
    part = _sheet_part("D-1", "DOWNSTAND", 2.0)
    assert g.provisional_blank_from_sheets(
        part, [_sheet(tmp_path, "d4", items, weight="0.6KG")]) is None
    assert "flat pattern" in part["_provisional_blank_refused"]


def test_a_figure_along_the_length_is_never_the_width_however_well_it_fits(tmp_path):
    """The real sheet also prints 31,7 along the strip; it fits the weight too (1.19x)."""
    items = _downstand_items() + [("31,7", 400, 250, 0)]
    blank = g.provisional_blank_from_sheets(_sheet_part("D-1", "DOWNSTAND", 2.0),
                                            [_sheet(tmp_path, "d6", items, weight="0.6KG")])
    assert blank and blank["width"] == 25.0


def test_the_weight_alone_never_picks_a_width(tmp_path):
    """With only a figure along the length fitting the weight, no width is chosen."""
    items = [i for i in _downstand_items() if i[0] != "25"] + [("31,7", 400, 250, 0)]
    part = _sheet_part("D-1", "DOWNSTAND", 2.0)
    assert g.provisional_blank_from_sheets(
        part, [_sheet(tmp_path, "d7", items, weight="0.6KG")]) is None


def test_the_weight_on_the_parts_own_sheet_beats_one_collected_from_an_assembly(tmp_path):
    """The record holds the assembly's 8.6 kg first; the sheet the blank is read from says 0.6."""
    part = _sheet_part("D-1", "DOWNSTAND", 2.0, weights=["8.6KG", "0.6KG"])
    blank = g.provisional_blank_from_sheets(
        part, [_sheet(tmp_path, "d5", _downstand_items(), weight="0.6KG")])
    assert blank and blank["width"] == 25.0


# ── a radius its flat cannot hold is rolled, read from its own sheet only ──────────────────

def _roll_summary(tmp_path, dn_on_sheet):
    sheet = _sheet(tmp_path, "r", _downstand_items(), weight="0.6KG", number=11, dn=dn_on_sheet)
    return {"pages": [sheet]}


def test_a_strip_with_a_radius_wider_than_itself_is_rolled(tmp_path):
    part = _sheet_part("D-1", "DOWNSTAND", 2.0, pages=[11], blank_length_mm=1435.2,
                       blank_width_mm=25.0)
    assert g.stamp_rolled_radii([part], _roll_summary(tmp_path, "D-1")) == ["D-1"]
    assert part["rolled_radius"]["radius_mm"] == 225.0
    assert part["operation_evidence"]["roll"]


def test_the_same_radius_on_a_plate_is_a_corner_of_its_profile(tmp_path):
    part = _sheet_part("D-1", "BASE PLATE", 2.0, pages=[11], blank_length_mm=1154.0,
                       blank_width_mm=450.0)
    assert g.stamp_rolled_radii([part], _roll_summary(tmp_path, "D-1")) == []


def test_a_radius_on_a_sheet_titled_for_another_part_is_not_this_parts(tmp_path):
    part = _sheet_part("D-1", "DOWNSTAND", 2.0, pages=[11], blank_length_mm=1435.2,
                       blank_width_mm=25.0)
    assert g.stamp_rolled_radii([part], _roll_summary(tmp_path, "ASM-9")) == []


def test_a_flat_unformed_part_is_not_rolled(tmp_path):
    items = [i for i in _downstand_items() if i[0] != "FLAT PATTERN"]
    summary = {"pages": [_sheet(tmp_path, "r2", items, number=11, dn="D-1")]}
    part = _sheet_part("D-1", "STRIP", 2.0, pages=[11], blank_length_mm=1435.2,
                       blank_width_mm=25.0)
    assert g.stamp_rolled_radii([part], summary) == []


def test_a_rolled_part_is_charged_on_the_roll_row():
    part = _sheet_part("D-1", "DOWNSTAND", 2.0, quantity=2, blank_length_mm=1435.2,
                       blank_width_mm=25.0, textual_operations=["laser_cutting"],
                       rolled_radius={"radius_mm": 225.0, "pages": [11], "why": "R225"},
                       operation_evidence={"roll": "R225 on its own sheet"})
    est = e.estimate_part(part, job_quantity=1)
    assert (est.get("labour_estimate") or {}).get("batch_hours", {}).get("roll", 0) > 0
    decs = {d["operation"]: d for d in rc.compile_job_route([part], {})["decisions"]}
    assert decs["roll"]["status"] == "required"
    assert W.OP_NAME_MAP.get("roll") == "Roll"


# ── a formed shape is folded from sheet unless a section is named ──────────────────────────

def test_an_angle_with_a_sheet_gauge_is_a_folded_sheet_part():
    part = _sheet_part("A-1", "RAIL BASE ANGLE", 3.0, materials=["MILD STEEL - RAW"],
                       blank_length_mm=250.0, blank_width_mm=48.0)
    assert not e._is_section_or_wire_candidate(part, "MILD_STEEL")
    e.estimate_part(part, job_quantity=1)
    assert part["fold_count_from_shape"] == {"shape": "ANGLE", "folds": 1}
    decs = {d["operation"]: d for d in rc.compile_job_route([part], {})["decisions"]}
    assert decs["folding"]["status"] == "required"
    assert "formed angle" in str(decs["folding"].get("evidence") or "")


@pytest.mark.parametrize("extra", [
    {"materials": ["MILD STEEL ANGLE"]},
    {"description": "BASE ANGLE 25X25X3"},
    {"section_stock": {"a": 25, "b": 25, "t": 3}},
])
def test_an_angle_whose_section_is_named_stays_a_section(extra):
    part = _sheet_part("A-2", "BASE ANGLE", 3.0, **extra)
    assert fs.formed_sheet_shape(part) is None
    assert e._is_section_or_wire_candidate(part, "MILD_STEEL")


def test_a_channel_is_two_folds_and_a_tube_is_never_a_formed_shape():
    assert fs.shape_folds(_sheet_part("C-1", "U-CHANNEL", 1.5)) == 2
    tube = _sheet_part("T-9", "RECT TUBE UPRIGHT", 2.0)
    assert fs.formed_sheet_shape(tube) is None
    assert e._is_section_or_wire_candidate(tube, "MILD_STEEL")


def test_a_formed_shape_sizes_its_blank_with_its_flange(tmp_path):
    sheet = _sheet(tmp_path, "angle", [("250", 500, 300, 0), ("23", 420, 340, 90)],
                   weight="0.2KG")
    blank = g.provisional_blank_from_sheets(_sheet_part("A-1", "BASE ANGLE", 3.0), [sheet])
    assert blank and blank["folds"] == 1 and blank["width"] > 23.0


# ── coating and material follow the assembly's members, through the compiled hierarchy ─────

def _graph(monkeypatch, parents):
    monkeypatch.setattr(e, "_compiled_parent_map", lambda parts, summary: parents)


def test_an_assemblys_coat_is_its_compiled_members_area(monkeypatch):
    asm = {"part_number": "ASM-1", "description": "SUPPORT", "owning_assembly": "ROOT",
           "textual_operations": ["powder_coating"], "quantity": 2}
    m1 = _sheet_part("M-1", "PLATE", 2.0, owning_assembly="ROOT", blank_length_mm=500.0,
                     blank_width_mm=100.0)
    _graph(monkeypatch, {"M-1": {"ASM-1"}})
    e.stamp_members_coated_area([asm, m1], {"pages": []})
    assert asm.get("_powder_members_coated_m2", 0) > 0, \
        "a member named only by the compiled graph is still a member"


def test_a_brushed_member_and_bought_hardware_stay_out_of_the_assemblys_coat(monkeypatch):
    """ROL prints the finish in the material field: STAINLESS STEEL - BRUSHED."""
    asm = {"part_number": "ASM-1", "textual_operations": ["powder_coating"], "quantity": 1}
    plate = _sheet_part("M-1", "PLATE", 2.0, materials=["MILD STEEL - RAW"],
                        blank_length_mm=500.0, blank_width_mm=100.0)
    strip = dict(_sheet_part("M-2", "ANTI SCRATCH STRIP", 3.0,
                             materials=["STAINLESS STEEL - BRUSHED"],
                             blank_length_mm=1200.0, blank_width_mm=40.0),
                 normalized_material="STAINLESS_STEEL")
    nut = {"part_number": "DIN 934 - M10", "description": "Hex Nut", "page_roles": ["bought_in"],
           "is_bought_in": True, "blank_length_mm": 20.0, "blank_width_mm": 20.0}
    _graph(monkeypatch, {"M-1": {"ASM-1"}, "M-2": {"ASM-1"}, "DIN 934 - M10": {"ASM-1"}})
    e.stamp_members_coated_area([asm, plate, strip, nut], {"pages": []})
    assert asm["_powder_members_coated_m2"] == pytest.approx(0.5 * 0.1 * 2)
    assert any("M-2" in x and "brushed" in x for x in asm.get("_powder_members_left_out", []))


def test_without_the_graph_the_root_owned_member_is_not_counted(monkeypatch):
    """The broken case the rail shipped with: owning_assembly is the root on every record."""
    asm = {"part_number": "ASM-1", "textual_operations": ["powder_coating"], "quantity": 2}
    m1 = _sheet_part("M-1", "PLATE", 2.0, owning_assembly="ROOT", blank_length_mm=500.0,
                     blank_width_mm=100.0)
    e.stamp_members_coated_area([asm, m1])
    assert not asm.get("_powder_members_coated_m2")


def test_an_assemblys_material_is_its_members_when_they_agree(monkeypatch):
    asm = {"part_number": "ASM-1"}
    sp.apply_field(asm, "normalized_material", "STAINLESS_STEEL", "drawing_deterministic")
    sp.apply_field(asm, "normalized_material", "STAINLESS_STEEL", "inference")
    kids = [_sheet_part("M-1", "ARM", 2.0), _sheet_part("M-2", "ANGLE", 3.0)]
    _graph(monkeypatch, {"M-1": {"ASM-1"}, "M-2": {"ASM-1"}})
    assert e.stamp_members_material([asm] + kids, {}) == ["ASM-1"]
    assert asm["normalized_material"] == "MILD_STEEL"


def test_members_that_disagree_decide_nothing_and_a_person_still_wins(monkeypatch):
    asm = {"part_number": "ASM-1", "normalized_material": "STAINLESS_STEEL"}
    kids = [_sheet_part("M-1", "ARM", 2.0), dict(_sheet_part("M-2", "STRIP", 3.0),
                                                normalized_material="STAINLESS_STEEL")]
    _graph(monkeypatch, {"M-1": {"ASM-1"}, "M-2": {"ASM-1"}})
    assert e.stamp_members_material([asm] + kids, {}) == []
    ruled = {"part_number": "ASM-2"}
    sp.apply_field(ruled, "normalized_material", "ACRYLIC", "estimator_confirmed")
    _graph(monkeypatch, {"M-1": {"ASM-2"}})
    assert e.stamp_members_material([ruled, kids[0]], {}) == []


# ── a numbered assembly is never a bought commodity ─────────────────────────────────────────

def test_a_customer_drawing_number_on_an_assembly_page_is_not_retagged_bought_in():
    from document_builder import _apply_post_build_fixes, _empty_part_record
    asm = _empty_part_record(part_number="ROL2021-2466")
    asm.update({"description": "MIDFLOOR RAIL", "page_roles": ["assembly"], "pages": [3]})
    loom = _empty_part_record(part_number="BI-50CMLOOM")
    loom.update({"description": "ELECTRICS LOOM 50CM", "page_roles": ["assembly"], "pages": [3]})
    _apply_post_build_fixes([asm, loom], {"pages": []})
    assert "bought_in" not in asm["page_roles"]
    assert "bought_in" in loom["page_roles"], "a described commodity is still recognised"


# ── each DRIL row names its own work ────────────────────────────────────────────────────────

def test_two_dril_rows_on_one_part_say_which_is_which():
    drill = W.labour_row_description("Drill (Acrylic)", "MILD STEEL", work_ops=["hole_machining"])
    tap = W.labour_row_description("Drill (Acrylic)", "MILD STEEL", work_ops=["tapping"])
    assert drill != tap
    assert "flow drilling" in drill and "tapping" in tap


# ── every required operation is charged once, covered, or asked ─────────────────────────────

def _job():
    from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two
    job = seventy_three_thirty_two()
    job["final_estimate"]["source"] = "excel_calculated"
    return job


def _decisions(job):
    return job["estimate_summary"]["canonical_route_shadow"]["decisions"]


def test_a_real_shaped_job_has_every_operation_on_a_row():
    cov = cf.operation_coverage(_job())
    assert cov["charged"] and not cov["uncovered"] and not cov["charged_twice"]


def test_a_required_operation_on_no_row_is_asked_with_its_department():
    job = _job()
    _decisions(job).append({"decision_id": "decision:roll-x", "operation": "roll",
                            "target_id": "7332-01-005", "status": "required",
                            "source": "inference"})
    cov = cf.operation_coverage(job)
    assert [(u["operation"], u["target"], u["department"]) for u in cov["uncovered"]] == \
        [("roll", "7332-01-005", "Roll")]
    asked = [d for d in cf.costed_job(job)["decisions_required"]
             if d.get("operation") == "roll"]
    assert asked and "on no charged row" in asked[0]["issue"]


def test_one_requirement_on_two_rows_of_one_department_is_asked():
    job = _job()
    accepted = job["estimate_summary"]["workbook_labour"]["rows"]
    src = next(r for r in accepted if r.get("decision_ids"))
    calc = next(r for r in job["final_estimate"]["labour_rows"]
                if int(r["workbook_row"]) == int(src["workbook_row"]))
    accepted.append(dict(src, workbook_row=999))
    job["final_estimate"]["labour_rows"].append(dict(calc, workbook_row=999))
    cov = cf.operation_coverage(job)
    assert any(set(t["rows"]) == {int(src["workbook_row"]), 999} or
               set(map(int, t["rows"])) == {int(src["workbook_row"]), 999}
               for t in cov["charged_twice"])
    assert any("is charged on 2 rows" in d["issue"]
               for d in cf.costed_job(job)["decisions_required"])


def test_one_requirement_on_two_rows_for_different_parts_is_two_stages_not_a_double_charge():
    job = _job()
    accepted = job["estimate_summary"]["workbook_labour"]["rows"]
    src = next(r for r in accepted if r.get("decision_ids"))
    calc = next(r for r in job["final_estimate"]["labour_rows"]
                if int(r["workbook_row"]) == int(src["workbook_row"]))
    accepted.append(dict(src, workbook_row=998, part_numbers=["7332-01-GA"]))
    job["final_estimate"]["labour_rows"].append(dict(calc, workbook_row=998))
    cov = cf.operation_coverage(job)
    assert not cov["charged_twice"]
    assert any(c.get("stages") == 2 for c in cov["charged"])


def test_a_ruled_out_operation_is_covered_by_its_ruling():
    job = _job()
    _decisions(job).append({"decision_id": "decision:fold-x", "operation": "folding",
                            "target_id": "7332-01-003", "status": "required"})
    for p in job["manufacturing_writeup"]["parts"]:
        if p["part_number"] == "7332-01-003":
            p["operations_ruled_out"] = {"folding": "flat plate — measured"}
    cov = cf.operation_coverage(job)
    assert any(c["operation"] == "folding" and c["target"] == "7332-01-003"
               and c["covered_by"] == "ruled out on the part" for c in cov["covered"])


def test_before_the_sheet_is_calculated_nothing_is_judged():
    job = _job()
    job["final_estimate"] = {}
    assert cf.operation_coverage(job) == {}


# ── reporting: charged, provisional, excluded, not verified ─────────────────────────────────

@pytest.mark.parametrize("line, part, kw, want", [
    ({"charged_ext_gbp": 4.0, "price_origin": {"firmness": cf.FIRM, "label": "nest"}}, {}, {},
     cf.CHARGED),
    ({"charged_ext_gbp": 4.0, "price_origin": {"firmness": cf.INDICATIVE_MARKET,
                                                "label": "researched market price"}}, {}, {},
     cf.PROVISIONAL),
    ({"charged_ext_gbp": 4.0, "price_origin": {"firmness": cf.FIRM}},
     {"_blank_provisional": {"basis": "printed_extents_provisional"}}, {}, cf.PROVISIONAL),
    ({"charged_ext_gbp": None, "kind": "assembly", "price_origin": {"firmness": cf.FIRM}}, {},
     {"engine_ext": 24.50}, cf.EXCLUDED),
    ({"charged_ext_gbp": None, "price_origin": {"firmness": cf.NIL, "label": "members'"}}, {}, {},
     cf.EXCLUDED),
    ({"charged_ext_gbp": None, "price_origin": {"firmness": cf.UNPRICED}}, {}, {},
     cf.NOT_VERIFIED),
    ({"charged_ext_gbp": 4.0}, {}, {"sheet_read_back": False}, cf.NOT_VERIFIED),
])
def test_each_line_has_one_charge_status(line, part, kw, want):
    assert cf.charge_status(line, part, **kw)["status"] == want


def test_an_uncharged_engine_figure_is_excluded_from_the_material_column(monkeypatch):
    import estimation_report as er
    job = _job()
    lines = cf.record_lines(job)
    target = next(pn for pn, l in lines.items() if l.get("charged_ext_gbp") is not None)
    real = cf.record_lines

    def _without_charge(source):
        out = real(source)
        out[target] = dict(out[target], charged_ext_gbp=None, charged_unit_gbp=None)
        return out
    monkeypatch.setattr(cf, "record_lines", _without_charge)
    prov = {p["part_number"].upper(): p for p in er.build_provenance(job)}
    row = prov[target]
    if row["engine_extended_cost"] <= 0:
        pytest.skip("the chosen line has no engine figure to exclude")
    assert row["extended_cost"] == 0.0
    assert row["charge_status"] == cf.EXCLUDED
    assert row["excluded_engine_gbp"] == round(row["engine_extended_cost"], 2)


def test_the_reconciliation_names_what_it_left_out_and_never_calls_an_excess_powder():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimation_report.py"),
               encoding="utf-8").read()
    assert "Not in the money:" in src and "EXCLUDED in the 'Charge status' column" in src
    assert "MORE than the sheet's material" in src


# ── the customer's page counts what it claims ───────────────────────────────────────────────

def test_the_route_claim_is_counted():
    import quote_story as qs
    made = [{"part_number": "A", "normalized_thickness_mm": 2, "blank_length_mm": 100},
            {"part_number": "B", "normalized_thickness_mm": 2}]
    facts = {"made": made, "parts_by_dept": {"Laser": {"A", "B"}}}
    assert qs._route_claim(facts).startswith("1 of 2 made parts")
    made[1]["blank_length_mm"] = 50
    assert qs._route_claim(facts).startswith("All 2 made parts")
