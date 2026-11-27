"""A missing price does not change what a part is made of (D-598o).

9287-10-GA's 18:23 live run, 24 Oct 2026: the base read SOLID SURFACE from the name its drawing
office gave the flat, and the pricing step costed it as 12 mm steel on the Sheet Steel block,
because the CAD model's library appearance said steel and steel has a rate. The labour rows and
the quote said solid surface; the charged cell said steel. The report led with "every
consistency check passed", the covering note's panel said nothing of it, and the base's two
nested outlines were read as a frame with no question asked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_job_merge                                              # noqa: E402
import estimator                                                      # noqa: E402
from invariants import check_owned_specifications_survive             # noqa: E402
from owned_specification import review_cautions                       # noqa: E402
from robust_ownership import release_focus_lines                      # noqa: E402
from source_precedence import apply_field                             # noqa: E402


def _base():
    part = {"part_number": "7777-10-005", "normalized_thickness_mm": 12.0}
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_applied_material")
    apply_field(part, "normalized_material", "SOLID SURFACE", "dxf_filename")
    return part


def test_a_drawing_office_material_is_not_priced_as_another():
    part = _base()
    assert part["normalized_material"] == "SOLID SURFACE"
    assert part["_displaced"]["normalized_material"][0]["value"] == "MILD_STEEL"
    assert estimator._material_we_can_actually_price(part, "SOLID SURFACE") == ("SOLID SURFACE", None)


def test_a_library_appearance_never_rescues_a_price():
    part = {"part_number": "X", "normalized_material": "ABS", "_displaced": {
        "normalized_material": [{"value": "MILD_STEEL", "source": "solidworks_applied_material"}]}}
    assert estimator._material_we_can_actually_price(part, "ABS") == ("ABS", None)


def test_a_specified_material_priced_as_another_blocks_release():
    part = _base()
    part["material_priced_as"] = {"arbitrated_material": "SOLID SURFACE",
                                  "priced_material": "MILD_STEEL"}
    found = check_owned_specifications_survive(
        {"manufacturing_writeup": {"parts": [part]}})
    assert found and found[0]["severity"] == "blocking"
    assert "priced as MILD_STEEL" in found[0]["message"]


def test_a_sheet_material_charged_on_the_steel_block_blocks_release():
    summary = {"manufacturing_writeup": {"parts": [_base()]},
               "final_estimate": {"material_rows": [
                   {"description": "7777-10-005  BASE", "block": "steel", "qty_per_unit": 1,
                    "total_value_gbp": 13.12, "charged_cell": "Estimate!M93"}]}}
    found = check_owned_specifications_survive(summary)
    assert any("on the steel block" in v["message"] for v in found)
    summary["final_estimate"]["material_rows"][0]["block"] = "other_sheet"
    assert not check_owned_specifications_survive(summary)


def test_an_appearance_reading_alone_is_not_held_to_the_drawing_office_rule():
    part = {"part_number": "X", "normalized_material": "MILD_STEEL"}
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_applied_material")
    part["material_priced_as"] = {"priced_material": "ACRYLIC"}
    assert not check_owned_specifications_survive({"manufacturing_writeup": {"parts": [part]}})


def test_the_report_does_not_praise_past_a_substitution():
    text = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")
    assert "every consistency check passed" not in text.lower()
    s = {"invariants": {"violations": [{"code": "material_priced_from_a_lower_ranked_reading",
                                        "severity": "warning",
                                        "message": "7777-10-005 priced as MILD_STEEL"}]}}
    assert review_cautions(s) == ["7777-10-005 priced as MILD_STEEL"]


def test_the_covering_note_names_what_blocks_and_what_is_unresolved():
    s = {"invariants": {"violations": [
        {"code": "owned_specification_not_preserved", "severity": "blocking",
         "message": "7777-10-005: the drawing office specifies SOLID SURFACE"},
        {"code": "x", "severity": "warning", "message": "not this one"}]},
         "material_charge_result": {"passed": False, "mode": "shadow"}}
    lines = release_focus_lines({}, s)
    said = " ".join(lines)
    assert all("§9" in line for line in lines)
    assert "Blocks release: 7777-10-005: the drawing office specifies SOLID SURFACE" in said
    assert "Not an acceptance pass: material_charge_result" in said
    assert "not this one" not in said


def _flat(tmp_path, name, inner):
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (303, 0), (303, 303), (0, 303)], close=True)
    a, b = inner
    msp.add_lwpolyline([(a, a), (b, a), (b, b), (a, b)], close=True)
    path = tmp_path / name
    doc.saveas(path)
    return path


def _questions(tmp_path, name, inner):
    pn = name.split("_")[0]
    out = drawing_job_merge.augment_summary_with_dxf(
        {"manufacturing_writeup": {"parts": [{"part_number": pn, "quantity": 1}]}, "pages": []},
        [_flat(tmp_path, name, inner)], reestimate=False)
    return [q for q in out["manufacturing_writeup"]["parts"][0].get("manufacturing_questions") or []
            if q.get("subject") == "nested_outline_frame_or_step"]


def test_an_outline_filling_the_blank_is_asked_frame_or_step(tmp_path):
    q = _questions(tmp_path, "7777-10-005_12mm SOLID SURFACE_REV[A].DXF", (8, 295))
    assert q and "not charged" in q[0]["assumption"]


def test_an_ordinary_cut_out_is_not_asked(tmp_path):
    assert not _questions(tmp_path, "7777-10-006_3mm MS_REV[A].DXF", (100, 200))
