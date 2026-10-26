"""A welded unit is welded once and coated once, as one piece (D-537).

0356455's 21:37 fresh-read book (£639.90 at one off): the read marked six member lines welded
and the unit only assembled and coated. D-531's rule — a welded unit owns its joints — waited
for the unit itself to be marked welded, so each member group paid its own Weld and Dress rows
(three of each, thirty minutes' set-up apiece). The route then hung 21 member pieces on the
powder line, and the workbook's POWDER row costed 0.0475 m2 — the wire alone — because the
costed records never carried their section size across the costing boundary, so every tube,
angle and channel added nothing. The wire bars themselves were "P.Coat charged with no coated
area" in the costing, which had no wire term. And the book listed five renamed lines as
dropped, "its material and work are missing", beside the same five added.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402

STEM = "0000-TESTRAIL"


def _line(name, form, size, length, qty, ops, wall=0):
    st = {"form": form, "length_mm": length}
    if form == "wire":
        st["wire_mm"] = size[0]
    else:
        st.update({"section_mm": list(size), "wall_mm": wall})
    return {"name": name, "kind": "fabricated", "material_guess": "MILD STEEL",
            "sighted_material": name, "quantity": qty, "stock": st,
            "assumed_blank_mm": {"length": length, "width": size[0], "thickness": 0},
            "operations": ops}


def _read(unit_ops=("assembly", "powder_coating")):
    weld = ["saw", "welding", "powder_coating"]
    return {"product": {"name": "TEST RAIL",
                        "assumed_overall_mm": {"height": 1700, "width": 700, "depth": 475}},
            "unit_operations": list(unit_ops),
            "parts": [_line("OVAL UPRIGHT", "oval_tube", (40, 20), 1625, 2, weld),
                      _line("TOP RAIL", "tube", (19,), 660, 1, weld),
                      _line("BASE ANGLE", "angle", (50, 50), 732, 2, weld, wall=5),
                      _line("HANGING WIRE BAR", "wire", (6,), 630, 4, ["saw", "powder_coating"]),
                      {"name": "SWIVEL CASTOR", "kind": "bought_in", "quantity": 4,
                       "operations": ["assembly"]}]}


def _build(answer):
    recs = cs.parts_from_concept(answer, STEM, sheet=True, brief="")
    unit = cs.unit_assembly_part(recs, answer, STEM)
    return unit, recs


def _by(recs, name):
    return next(r for r in recs if r["description"] == name)


def _route(unit, recs):
    import route_compiler as rc
    r = rc.compile_job_route([unit] + recs, {})
    req = {}
    for d in r["decisions"]:
        if d["status"] == "required":
            req.setdefault(d["operation"], set()).add(d["target_id"])
    return r, req


# ── welded once ──────────────────────────────────────────────────────────────────────────

def test_members_welded_to_each_other_make_the_unit_welded():
    unit, recs = _build(_read())
    assert "welding" in unit["inferred_operations"]
    assert any("welded as a unit" in f for f in unit["review_flags"])
    assert unit["weld_joint_count"] == (2 + 1 + 2) - 1
    for name in ("OVAL UPRIGHT", "TOP RAIL", "BASE ANGLE"):
        assert "welding" not in _by(recs, name)["inferred_operations"]
        assert _by(recs, name)["weld_charged_on"] == unit["part_number"]
    _r, req = _route(unit, recs)
    assert req["welding"] == {unit["part_number"]}


def test_one_welded_line_does_not_make_a_welded_unit():
    answer = _read()
    for p in answer["parts"][1:3]:
        p["operations"] = ["saw", "powder_coating"]
    unit, recs = _build(answer)
    assert "welding" not in unit.get("inferred_operations", [])
    assert "welding" in _by(recs, "OVAL UPRIGHT")["inferred_operations"]


# ── coated once, as the weldment ─────────────────────────────────────────────────────────

def test_a_welded_member_is_coated_with_the_unit_and_a_loose_one_on_its_own():
    unit, recs = _build(_read(unit_ops=("assembly",)))
    assert "powder_coating" in unit["inferred_operations"]
    for name in ("OVAL UPRIGHT", "TOP RAIL", "BASE ANGLE"):
        rec = _by(recs, name)
        assert "powder_coating" not in rec["inferred_operations"]
        assert rec["coat_charged_on"] == unit["part_number"]
    bar = _by(recs, "HANGING WIRE BAR")
    assert "powder_coating" in bar["inferred_operations"] and not bar.get("coat_charged_on")
    _r, req = _route(unit, recs)
    assert req["powder_coating"] == {unit["part_number"], bar["part_number"]}


def test_the_powder_line_holds_the_weldment_and_the_loose_bars_once_each():
    import estimator as E
    import wb_populate as wb
    unit, recs = _build(_read())
    r, _req = _route(unit, recs)
    summary = {"declared_product": unit["part_number"],
               "manufacturing_writeup": {"parts": [unit] + recs},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": [],
               "assumed_job_quantity": 1, "canonical_route_shadow": r}
    pes = E.estimate_document([unit] + recs, summary=summary)["part_estimates"]
    says = wb.route_coated_membership(wb.parts_the_route_says_are_coated(summary))
    upright = next(p for p in pes if p["description"] == "OVAL UPRIGHT")
    assert upright["section_stock"]["a"] == 40, "the section crosses the costing boundary"
    # the weldment's area is its welded members' outer surfaces — not the loose bars
    members = unit["_powder_members_m2"]
    bar_pn = _by(recs, "HANGING WIRE BAR")["part_number"].upper()
    assert bar_pn not in members and len(members) == 3
    sheet = wb.coated_sheet_area_m2(pes, says)
    assert abs(sheet - unit["_powder_members_coated_m2"]) < 1e-6 and sheet > 0.6
    # the loose bars are coated on their own line: pi x 6 x 630 each, four of them
    bar = next(p for p in pes if p["description"] == "HANGING WIRE BAR")
    det = bar["process_estimate"]["powder_coating_detail"]
    assert abs(det["coated_m2"] - 3.14159265 * 0.006 * 0.630) < 1e-4
    # and no section is summed a second time beside the weldment
    assert sum(wb.section_coated_area_m2(p) for p in pes if says(p)) == 0


def test_a_section_the_route_coats_on_its_own_line_now_adds_its_surface():
    import wb_populate as wb
    pe = {"part_number": "X1", "quantity": 2,
          "section_stock": {"a": 40, "b": 20, "length_mm": 1000, "profile_form": "OVAL"}}
    area = wb.section_coated_area_m2(pe)
    assert 0.19 < area < 0.20                     # two ovals, about 0.0969 m2 each


# ── the change list says renamed, not dropped ────────────────────────────────────────────

def test_a_renamed_line_is_renamed_and_a_second_line_of_one_name_is_kept():
    prev = {"parts": [{"name": "MAIN VERTICAL UPRIGHT", "kind": "fabricated", "quantity": 2},
                      {"name": "19MM ROUND TUBE MEMBER", "kind": "fabricated", "quantity": 2},
                      {"name": "BASE ANGLE FRAME", "kind": "fabricated", "quantity": 2},
                      {"name": "125MM SWIVEL CASTOR", "kind": "bought_in", "quantity": 4},
                      {"name": "FLAT BAR FOOT", "kind": "fabricated", "quantity": 2}]}
    new = {"parts": [{"name": n, "kind": k, "quantity": q, "assumed_blank_mm": {"length": L}}
                     for n, k, q, L in (
                         ("MAIN VERTICAL OVAL UPRIGHT", "fabricated", 2, 1723),
                         ("19 MM ROUND TUBE VERTICAL MEMBER", "fabricated", 2, 1723),
                         ("BASE ANGLE FRAME MEMBER", "fabricated", 2, 732),
                         ("BASE ANGLE FRAME MEMBER", "fabricated", 2, 475),
                         ("125 MM SWIVEL CASTOR", "bought_in", 4, 0))]}
    changes = cs.bill_changes(prev, new)
    assert "renamed: MAIN VERTICAL UPRIGHT → MAIN VERTICAL OVAL UPRIGHT" in changes
    assert "renamed: 19MM ROUND TUBE MEMBER → 19 MM ROUND TUBE VERTICAL MEMBER" in changes
    assert "renamed: BASE ANGLE FRAME → BASE ANGLE FRAME MEMBER" in changes
    assert "added: BASE ANGLE FRAME MEMBER x2" in changes
    assert not any("CASTOR" in c for c in changes
                   if c.startswith(("renamed", "added", "dropped"))), \
        "19MM and 19 MM are one spelling — the same line, not a rename"
    assert [c for c in changes if c.startswith("dropped: ")] == ["dropped: FLAT BAR FOOT x2"]
