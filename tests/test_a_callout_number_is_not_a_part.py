"""A callout number is not a part, its work is kept, and a list line ends where the next
begins (D-533).

0356455 small repro rail, 20:46 book: the materials list reads "6. 2MM U-CHANNEL BAR CONNECTOR
OTHER SIDE WELDED TO UPRIGHT". The drawing-text extract keyed that weld to part "6" — the
list's item number — and the sheet charged a Weld (CO2) row (£22.33, 30 min set-up) on a part
that does not exist, beside the unit's own weld rows.

The reviewer's terms: keep the guard narrow (a part genuinely numbered "6" keeps its route);
do not lose the stated weld — assign it to the component the line names, charged once; and
separate list items without splitting a wrapped line.

And the brief written for it in list form lost a stated count: flattened, "- four wire hooks,
one on each end of each bar" ran into "- four U-channel bar connectors" as one clause, so the
first line's "each" cancelled the second line's count.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import invariants  # noqa: E402
import route_compiler as rc  # noqa: E402

LINE = "2MM U-CHANNEL BAR CONNECTOR OTHER SIDE WELDED TO UPRIGHT"


def _parts(unit_welded=True):
    return [{"part_number": "J-CPT00", "description": "RAIL — unit assembly",
             "is_assembly_parent": True, "quantity": 1,
             "assembly_children": ["J-CPT01", "J-CPT05"],
             "inferred_operations": ["assembly"] + (["welding"] if unit_welded else [])},
            {"part_number": "J-CPT01", "description": "MAIN VERTICAL UPRIGHT", "quantity": 2,
             "normalized_material": "MILD STEEL", "materials": ["40 X 20 OVAL"],
             "inferred_operations": ["saw"], "parent_assemblies": ["J-CPT00"]},
            {"part_number": "J-CPT05", "description": "U-CHANNEL CONNECTOR", "quantity": 4,
             "normalized_material": "MILD STEEL", "materials": ["2MM U-CHANNEL BAR CONNECTOR"],
             "inferred_operations": ["saw"], "parent_assemblies": ["J-CPT00"]}]


def _extract(with_line=True):
    ext = {"routes": [{"operation": "welding", "part_numbers": ["6"],
                       "evidence": "OTHER SIDE WELDED TO UPRIGHT"}]}
    if with_line:
        ext["bom"] = [{"item_number": "6", "description": LINE}]
    return ext


def _welds(r):
    return {d["target_id"]: d for d in r["decisions"] if d["operation"] == "welding"}


def test_no_charge_is_owned_by_a_bare_list_number():
    for unit_welded in (True, False):
        r = rc.compile_job_route(_parts(unit_welded), _extract())
        assert "6" not in _welds(r)


def test_the_stated_weld_is_charged_once_on_the_welded_unit_and_said_on_the_connector():
    w = _welds(rc.compile_job_route(_parts(), _extract()))
    assert w["J-CPT00"]["status"] == "required"
    assert w["J-CPT05"]["status"] == "not_applicable"
    assert "item 6" in w["J-CPT05"]["reason"] and "J-CPT00" in w["J-CPT05"]["reason"]
    assert sum(1 for d in w.values() if d["status"] == "required") == 1


def test_the_stated_weld_is_charged_on_the_connector_where_no_assembly_welds_it():
    w = _welds(rc.compile_job_route(_parts(unit_welded=False), _extract()))
    assert w["J-CPT05"]["status"] == "required" and "J-CPT00" not in w


def test_a_line_that_names_no_part_is_not_charged_and_is_asked():
    r = rc.compile_job_route(_parts(), _extract(with_line=False))
    assert "6" not in _welds(r)
    assert any(i.get("code") == "route_participant_is_a_callout_number" for i in r["issues"])
    found = invariants.check_a_callout_weld_is_assigned({"canonical_route_shadow": r})
    assert found and found[0]["detail"]["needs_ruling"] and "item 6" in found[0]["message"]


def test_a_part_genuinely_numbered_six_keeps_its_route():
    parts = _parts(unit_welded=False) + [{"part_number": "6", "description": "BRACKET",
                                          "quantity": 1, "normalized_material": "MILD STEEL"}]
    r = rc.compile_job_route(parts, {"routes": [{"operation": "welding", "part_numbers": ["6"]}]})
    assert _welds(r)["6"]["status"] == "required"
    assert not [i for i in r["issues"] if "callout" in str(i.get("code"))]


# ── list items stay separate; a wrapped line stays one item ─────────────────────────────

def _counts(brief):
    return {(s["count"], " ".join(s["words"])) for s in cs.brief_stated_counts(brief)}


def test_each_list_line_keeps_its_own_count():
    got = _counts("Construction from the views:\n"
                  "- four wire hooks, 6 mm wire, one on each end of each adjustable bar\n"
                  "- four U-channel bar connectors, 2 mm, welded to the uprights\n"
                  "- two uprights, 40 × 20 oval tube")
    assert (4, "u-channel bar connectors") in got and (2, "uprights") in got


def test_a_wrapped_line_belongs_to_its_item():
    got = _counts("- four wire hooks, 6 mm wire, one on each end\n"
                  "  of each adjustable bar\n"
                  "- two\n"
                  "  uprights, 40 × 20 oval tube, 1625 mm long\n"
                  "- four U-channel bar connectors, 2 mm, welded\n"
                  "  2 mm thick to the uprights")
    assert (2, "uprights") in got, "a count wrapped onto the next line is still the item's"
    assert (4, "u-channel bar connectors") in got


def test_a_numbered_materials_list_still_states_no_counts():
    assert cs.brief_stated_counts(
        "Materials:\n1. 40 × 20 oval tube frame\n2. 19 mm round tube rails\n"
        "4. 60 x 40 angle runners") == []
