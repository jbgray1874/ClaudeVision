"""12665-01-GA, the D-505/506 re-run (D-508). Six faults, each a generic rule:

A  a catalogue price the plausibility guard REFUSED was charged anyway by a later pass
   (two LIGHTING lines at £1,086.34 each, the handed twin at £42);
B  a handed copy reached costing with no steel because its base got its provisional blank
   after the mirror rule had run;
C  the weight check read the wrong field and never ran — and when it runs, heavier is
   asked, only an impossible lighter blank is refused;
D  two fascia ASSEMBLIES were given "provisional blanks" and the estimator asked for a flat;
E  an acrylic back plate read at 1737 x 1684.7 mm inside a 400 x 251.5 mm assembly;
F  one code at two item numbers for two different things was summed into one line.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

fitz = pytest.importorskip("fitz")

import detail_page_geometry as dpg  # noqa: E402
import estimator  # noqa: E402
import source_precedence as sp  # noqa: E402
from route_compiler import _bom_stated_edges, same_item_described  # noqa: E402


def _sheet(tmp_path, words, name="sheet.pdf", page_number=8):
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)
    for (x, y), text, rot in words:
        page.insert_text((x, y), text, fontsize=9, rotate=rot)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return {"page_number": page_number, "source_pdf_path": str(path), "source_page_number": 1}


# ── A: a held price stays held ──────────────────────────────────────────────────────────

class _FakeService:
    def __init__(self, price):
        self.price = price

    def _select_anchor_price_source(self, _part):
        return {"unit_price_gbp": self.price, "source": "web_ai_fallback",
                "supplier_name": "market research"}


def _udef_hit(_req):
    return {"selected": {"price": 1086.34, "source": "udef",
                         "metadata": {"supplier_name": "Udef parts table"}}}


def test_a_refused_catalogue_figure_is_passed_over_by_every_later_lookup(monkeypatch):
    monkeypatch.setattr(estimator, "get_best_price", _udef_hit)
    monkeypatch.setattr(estimator, "_get_pricing_service", lambda: _FakeService(42.0))
    line = {"part_number": "9001-02-02X", "description": "LIGHTING"}
    assert estimator._resolve_part_system_cost(dict(line))["applied_unit_cost"] == 1086.34
    held = dict(line, risk_flags=["implausible_system_cost_rejected_price_manually:GBP1086"])
    out = estimator._resolve_part_system_cost(held)
    assert out["applied_unit_cost"] == 42.0, "the refused figure came back"
    assert held["_held_price_passed_over"] == [1086.34]
    exact = dict(line, _rejected_system_costs=[1086.34])
    assert estimator._resolve_part_system_cost(exact)["applied_unit_cost"] == 42.0


def test_the_same_figure_from_the_next_rung_is_still_refused(monkeypatch):
    monkeypatch.setattr(estimator, "get_best_price", _udef_hit)
    monkeypatch.setattr(estimator, "_get_pricing_service", lambda: _FakeService(1086.34))
    held = {"part_number": "9001-02-02X", "description": "LIGHTING",
            "_rejected_system_costs": [1086.34]}
    out = estimator._resolve_part_system_cost(held)
    assert out.get("applied_unit_cost") != 1086.34


def test_the_held_figure_reads_in_plain_english():
    import plain_english as pe
    code = "implausible_system_cost_rejected_price_manually:GBP1086"
    assert "held" in pe.label(code).lower() and "No plain-English" not in pe.explain(code)


def test_two_hands_priced_far_apart_are_both_asked_and_neither_is_changed():
    def _pe(pn, unit, src):
        return {"part_number": pn, "manufacturing_questions": None,
                "material_estimate": {"unit_material_cost_gbp": unit,
                                      "price_source": {"supplier_name": src}}}
    base, hand = _pe("9001-03-02X", 1086.34, "catalogue"), _pe("9001-03-02X-H", 42.0, "RS")
    assert estimator.question_divergent_hands([base, hand]) == 1
    for line in (base, hand):
        q = line["manufacturing_questions"][0]["issue"]
        assert "1,086.34" in q and "42.00" in q
    assert base["material_estimate"]["unit_material_cost_gbp"] == 1086.34
    near = [_pe("9001-03-02X", 40.0, "a"), _pe("9001-03-02X-H", 42.0, "b")]
    assert estimator.question_divergent_hands(near) == 0


# ── B: the other hand takes its base's provisional blank ────────────────────────────────

def _provisional_base():
    base = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "normalized_finish": "POWDER COATED"}
    dpg._stamp_provisional(base, {"length": 1064.8, "width": 324.0, "working": "its sheet",
                                  "folds": 2}, "no overall printed")
    return base


def test_a_hand_with_nothing_of_its_own_takes_its_bases_provisional_blank_and_stock():
    base, hand = _provisional_base(), {"part_number": "9001-03-01M-H"}
    assert dpg.mirror_provisional_blanks([base, hand]) == ["9001-03-01M-H"]
    assert (hand["blank_length_mm"], hand["blank_width_mm"]) == (1064.8, 324.0)
    assert hand["normalized_geometry"]["blank_length_mm"] == 1064.8
    assert hand["normalized_material"] == "MILD_STEEL" and hand["normalized_thickness_mm"] == 1.5
    assert hand["_blank_provisional"]["mirrored_from"] == "9001-03-01M"
    assert any("MIRRORED" in f for f in hand["review_flags"])
    assert hand["manufacturing_questions"]


def test_a_hand_that_states_its_own_size_or_stock_keeps_it():
    base = _provisional_base()
    hand = {"part_number": "9001-03-01M-H", "normalized_thickness_mm": 2.0}
    sp.apply_field(hand, "blank_length_mm", 900.0, "pdf_overall_dims")
    sp.apply_field(hand, "blank_width_mm", 300.0, "pdf_overall_dims")
    assert dpg.mirror_provisional_blanks([base, hand]) == []
    assert hand["blank_length_mm"] == 900.0 and hand["normalized_thickness_mm"] == 2.0


# ── C: the weight is read where it is, and it checks rather than decides ────────────────

def test_the_weight_check_now_runs_on_a_title_block_weight(tmp_path):
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    part = {"part_number": "9001-05-02M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "weights": ["7kg"]}
    blank = dpg.provisional_blank_from_sheets(part, [page])
    assert blank and "agrees with the stated 7 kg" in blank["working"]


def test_the_mass_note_no_longer_says_the_sheet_charges_the_weight():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "The MATERIAL is costed from the printed weight;" not in src
    assert "the sheet charges the blank's share of a sheet" in src


# ── D: an assembly of made parts gets no blank of its own ───────────────────────────────

def _fascia_job(tmp_path):
    asm_page = _sheet(tmp_path, [((200, 200), "400", 0), ((150, 400), "251.5", 90)],
                      name="asm.pdf", page_number=16)
    plate_page = _sheet(tmp_path, [((200, 200), "1737", 0), ((150, 400), "1684.7", 90)],
                        name="plate.pdf", page_number=13)
    asm = {"part_number": "9001-04-201", "description": "NEW FASCIA ASSEMBLY", "pages": [16]}
    fascia = {"part_number": "9001-04-02M", "bom_parent": "9001-04-201",
              "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5}
    plate = {"part_number": "9001-04-03A", "bom_parent": "9001-04-201",
             "normalized_material": "ACRYLIC", "normalized_thickness_mm": 3.0, "pages": [13]}
    sp.apply_field(plate, "blank_length_mm", 1737.0, "drawing_deterministic")
    sp.apply_field(plate, "blank_width_mm", 1684.7, "drawing_deterministic")
    magnet = {"part_number": "MAGNET21", "bom_parent": "9001-04-201",
              "description": "NEODYMIUM BAR MAGNET"}
    summary = {"pages": [asm_page, plate_page], "document_analysis": {"bom_rows": [
        {"part_number": "9001-04-02M", "bom_parent": "9001-04-201"},
        {"part_number": "9001-04-03A", "bom_parent": "9001-04-201"},
        {"part_number": "MAGNET21", "bom_parent": "9001-04-201"}]}}
    return [asm, fascia, plate, magnet], summary


def test_an_assembly_of_made_parts_is_given_no_blank_and_keeps_its_outline(tmp_path):
    parts, summary = _fascia_job(tmp_path)
    asm = parts[0]
    dpg.apply_detail_page_geometry(parts, summary)
    assert not asm.get("blank_length_mm") and not asm.get("_blank_provisional")
    assert asm["_sheet_envelope_mm"]["length"] == 400.0
    assert asm["_assembly_of_made_parts"] == ["9001-04-02M", "9001-04-03A"]
    assert not asm.get("manufacturing_questions")


def test_a_cut_part_that_lists_only_hardware_is_still_a_part():
    panel = {"part_number": "9001-05-01M"}
    nut = {"part_number": "PEM-M6", "bom_parent": "9001-05-01M", "description": "PEM NUT M6"}
    assert dpg.made_children(panel, [panel, nut], {}) == []
    loose = {"part_number": "9001-05-201"}
    assert dpg.made_children(loose, [loose, nut], {}) == []


# ── E: a part read larger than its assembly ─────────────────────────────────────────────

def test_a_part_read_larger_than_its_assembly_is_costed_on_that_assembly_and_asked(tmp_path):
    parts, summary = _fascia_job(tmp_path)
    dpg.apply_detail_page_geometry(parts, summary)
    plate = parts[2]
    assert dpg.check_parts_against_their_assembly(parts, summary) == ["9001-04-03A"]
    assert (plate["blank_length_mm"], plate["blank_width_mm"]) == (400.0, 251.5)
    assert plate["normalized_geometry"]["blank_length_mm"] == 400.0
    assert sp.source_of(plate, "blank_length_mm") == dpg.ASSEMBLY_ALLOWANCE_SOURCE
    assert plate["_blank_capped_to_assembly"]["read_mm"] == [1737.0, 1684.7]
    assert "LARGER THAN ITS ASSEMBLY" in plate["blank_inferred_reason"]
    assert plate["manufacturing_questions"]


def test_a_part_inside_its_assembly_and_a_measured_one_are_left_alone(tmp_path):
    parts, summary = _fascia_job(tmp_path)
    dpg.apply_detail_page_geometry(parts, summary)
    plate = parts[2]
    sp.apply_field(plate, "blank_length_mm", 420.0, "estimator_confirmed")
    sp.apply_field(plate, "blank_width_mm", 260.0, "estimator_confirmed")
    assert dpg.check_parts_against_their_assembly(parts, summary) == []
    assert plate["blank_length_mm"] == 420.0


def test_the_outline_is_developed_for_the_parts_own_folds(tmp_path):
    parts, summary = _fascia_job(tmp_path)
    dpg.apply_detail_page_geometry(parts, summary)
    plate = parts[2]
    plate["fold_count_textual"] = 4
    plate["blank_length_mm"], plate["blank_width_mm"] = 480.0, 330.0     # 400+4x25 = 500
    plate["normalized_geometry"] = {}
    assert dpg.check_parts_against_their_assembly(parts, summary) == []


def test_the_allowance_ranks_above_the_reading_and_below_a_person():
    assert sp.rank("drawing_deterministic") < sp.rank(dpg.ASSEMBLY_ALLOWANCE_SOURCE) \
        < sp.rank("estimator_read_drawing")


# ── F: one code, two items ──────────────────────────────────────────────────────────────

def _rows(*rows):
    return [{"part_number": c, "bom_parent": "9001-01-GA", "quantity": q, "item_number": i,
             "description": d} for c, q, i, d in rows]


def test_two_different_things_under_one_code_are_not_summed():
    known = {"3987-GA", "9001-01-GA"}
    clashes = []
    edges = _bom_stated_edges(_rows(("3987-GA", 9, "7", "HOOK SECURITY STOP LOCK - 6mm"),
                                    ("3987-GA", 10, "8", "POWERTOOL PIN")),
                              {}, known, [], incompatible=clashes)
    assert edges == [("3987-GA", "9001-01-GA", 9.0)]
    assert clashes and clashes[0]["other"] == "POWERTOOL PIN" and not clashes[0]["relinked_to"]


def test_a_row_whose_words_spell_another_part_is_linked_to_it():
    known = {"3987-GA", "9001-01-GA", "P/P-HOOK-SECURITY-STOP-LOCK"}
    clashes = []
    edges = _bom_stated_edges(_rows(("3987-GA", 9, "7", "HOOK SECURITY STOP LOCK - 6mm"),
                                    ("3987-GA", 10, "8", "POWERTOOL PIN")),
                              {}, known, [], incompatible=clashes)
    assert sorted(edges) == [("3987-GA", "9001-01-GA", 10.0),
                             ("P/P-HOOK-SECURITY-STOP-LOCK", "9001-01-GA", 9.0)]
    assert clashes[0]["relinked_to"] == "P/P-HOOK-SECURITY-STOP-LOCK"


def test_a_handed_pair_and_a_misspelling_still_add():
    known = {"A-01M", "9001-01-GA"}
    edges = _bom_stated_edges(_rows(("A-01M", 1, "1", "SIDE PANEL LH"),
                                    ("A-01M", 1, "3", "SIDE PANEL RH")), {}, known, [])
    assert edges == [("A-01M", "9001-01-GA", 2.0)]
    assert same_item_described("SIDE PANNEL", "SIDE PANEL")
    assert same_item_described("", "POWERTOOL PIN")


def test_the_clash_reaches_the_line_as_a_question():
    from route_compiler import apply_canonical_evidence_to_parts
    parts = [{"part_number": "9001-01-GA"},
             {"part_number": "3987-GA", "description": "POWERTOOL PIN"}]
    bom = [{"part_number": "9001-01-GA"},
           {"part_number": "3987-GA", "bom_parent": "9001-01-GA", "quantity": 9,
            "item_number": "7", "description": "HOOK SECURITY STOP LOCK - 6mm"},
           {"part_number": "3987-GA", "bom_parent": "9001-01-GA", "quantity": 10,
            "item_number": "8", "description": "POWERTOOL PIN"}]
    apply_canonical_evidence_to_parts(parts, {}, bom, ["9001-01-GA"], {}, summary={})
    qs = parts[1].get("manufacturing_questions") or []
    assert any("two different things" in q["issue"] for q in qs)
