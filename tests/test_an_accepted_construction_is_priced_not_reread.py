"""An accepted construction is priced, not re-read (D-534).

0356455's first book: wire hooks read as whole adjustable bars, a phantom pair of 1723 mm round
tubes, the flat-bar cross-members missing. The reviewer: "verify the member schedule against
the PDF, then replay that accepted construction through pricing — not repeatedly ask Grok for
another fresh design." The answers file corrects a line the read made; it cannot add a missed
line, remove an invented one or change what a line is cut from. A member schedule a person has
checked, filed beside the pack in the read's own shape, is the read: priced by every rule the
model's answer would be, and the model is not asked.

Also: a member whose weld the unit now charges (D-531) is still welded — it takes no fixings.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402

JOB = "0000-TESTRAIL"


def _schedule(**over):
    data = {"accepted_by": "J. Estimator", "accepted_on": "2026-10-14",
            "basis": "member schedule read off the GA",
            "product": {"name": "TEST RAIL",
                        "assumed_overall_mm": {"height": 1700, "width": 475, "depth": 730}},
            "unit_operations": ["welding", "assembly", "powder_coating"],
            "parts": [
                {"name": "UPRIGHT", "kind": "fabricated", "material_guess": "MILD STEEL",
                 "sighted_material": "40 X 20 OVAL", "quantity": 2,
                 "stock": {"form": "oval_tube", "section_mm": [40, 20], "length_mm": 1625},
                 "assumed_blank_mm": {"length": 1625, "width": 40, "thickness": 20},
                 "operations": ["saw", "welding", "powder_coating"]},
                {"name": "BASE CROSS BAR", "kind": "fabricated", "material_guess": "MILD STEEL",
                 "sighted_material": "50MM FLATBAR 10MM THICK", "quantity": 2,
                 "stock": {"form": "flat_bar", "section_mm": [50, 10], "length_mm": 520},
                 "assumed_blank_mm": {"length": 520, "width": 50, "thickness": 10},
                 "operations": ["saw", "welding", "powder_coating"]},
                {"name": "125MM SWIVEL CASTOR", "kind": "bought_in", "quantity": 4,
                 "operations": ["assembly"]}],
            "excluded": ["the tote crate drawn on the base"]}
    data.update(over)
    return data


def _file(tmp_path, data, name=f"{JOB}_construction.json"):
    (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_an_accepted_schedule_is_found_and_becomes_the_read(tmp_path):
    ans, f, problems = cs.find_accepted_construction([_file(tmp_path, _schedule())], job=JOB)
    assert ans and not problems and Path(f).name == f"{JOB}_construction.json"
    assert [p["name"] for p in ans["parts"]] == ["UPRIGHT", "BASE CROSS BAR", "125MM SWIVEL CASTOR"]
    assert ans["accepted_construction"]["accepted_by"] == "J. Estimator"
    assert ans["accepted_construction"]["excluded"] == ["the tote crate drawn on the base"]


def test_the_folder_name_and_the_plain_name_are_found_too(tmp_path):
    folder = tmp_path / JOB
    folder.mkdir()
    _file(folder, _schedule(), name=f"{JOB}_construction.json")
    assert cs.find_accepted_construction([folder])[0]
    other = tmp_path / "plain"
    other.mkdir()
    _file(other, _schedule(), name="construction.json")
    assert cs.find_accepted_construction([other])[0]


def test_a_draft_nobody_accepted_is_refused_by_name(tmp_path):
    ans, f, problems = cs.find_accepted_construction(
        [_file(tmp_path, _schedule(accepted_by="DRAFT — to check"))], job=JOB)
    assert ans is None and f and any("accepted_by" in p for p in problems)


def test_a_price_in_a_construction_is_refused(tmp_path):
    data = _schedule()
    data["parts"][2]["unit_price_gbp"] = 6.5
    ans, _f, problems = cs.find_accepted_construction([_file(tmp_path, data)], job=JOB)
    assert ans is None and any("money" in p for p in problems)


def test_a_line_with_no_quantity_is_refused(tmp_path):
    data = _schedule()
    data["parts"][0]["quantity"] = 0
    assert cs.find_accepted_construction([_file(tmp_path, data)], job=JOB)[0] is None


def test_no_file_reads_as_usual(tmp_path):
    assert cs.find_accepted_construction([tmp_path], job=JOB) == (None, "", [])


def test_the_schedule_prices_through_the_ordinary_mapper(tmp_path):
    ans = cs.find_accepted_construction([_file(tmp_path, _schedule())], job=JOB)[0]
    recs = cs.parts_from_concept(ans, "J")
    up = next(r for r in recs if r["description"] == "UPRIGHT")
    bar = next(r for r in recs if r["description"] == "BASE CROSS BAR")
    assert up["section_stock"]["profile_form"] == "OVAL" and up["quantity"] == 2
    assert bar["section_stock"]["profile_form"] == "FLAT"


def test_the_run_looks_for_the_schedule_before_it_asks_the_model():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
               encoding="utf-8").read()
    i = src.index("concept_scan.find_accepted_construction(")
    assert i < src.index("concept_scan.read_sheet_concept(")
    assert i < src.index("concept_scan.read_concept(")
    assert "ACCEPTED CONSTRUCTION REFUSED" in src


def test_a_member_whose_weld_the_unit_charges_takes_no_fixings(tmp_path):
    ans = cs.find_accepted_construction([_file(tmp_path, _schedule())], job=JOB)[0]
    recs = cs.parts_from_concept(ans, "J")
    unit = cs.unit_assembly_part(recs, ans, "J")
    assert "welding" in unit["inferred_operations"]
    assert all(r.get("weld_charged_on") == unit["part_number"]
               for r in recs if r.get("concept_kind") == "fabricated")
    mech = cs.mechanically_fitted(recs)
    assert mech["fixings"] == 4 * 4, "the castors only — the welded members are not screwed on"
