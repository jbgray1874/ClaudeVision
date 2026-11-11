"""12773-01-GA 19:39 (reviewer, 11 Nov 2026): one uncharged component and three required
operations with no sheet row.

The bill printed "12773-03-203.SLDPRT1" where the hierarchy holds 12773-03-203: two parts in
the graph, one priced, the other "on the bill, no line on the sheet". And the costing took
deburring and separate drilling off three MDF parts, while the route still called them required."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import route_compiler as rc  # noqa: E402


def test_a_model_file_name_cleans_to_the_part_number():
    assert rc.clean_part_number("12773-03-203.SLDPRT1") == "12773-03-203"
    assert rc.clean_part_number("12773-03-101.sldasm") == "12773-03-101"
    assert rc.clean_part_number("12773-03-203.SLDPRT12") == "12773-03-203"
    assert rc.spelling_key("12773-03-203.SLDPRT1") == rc.spelling_key("12773-03-203")


def test_a_code_that_only_looks_like_one_is_left_alone():
    assert rc.clean_part_number("M6 X 1.5") == "M6 X 1.5"
    assert rc.clean_part_number("FIXING1180") == "FIXING1180"
    assert rc.clean_part_number(".SLDPRT") == ".SLDPRT"


def _decision(op, target="P1"):
    return SimpleNamespace(status=rc.REQUIRED, scope="part", target_id=target, operation=op,
                           reason="read", field_provenance={})


def test_a_boards_dropped_deburr_and_drilling_are_not_required():
    raw = {"P1": {"part_number": "P1", "normalized_material": "MDF", "description": "SWIVEL PLATE",
                  "operations_ruled_out": {
                      "deburring": "board is not deburred — its edges are banded or finished",
                      "hole_machining": "holes in a CNC-routed board are cut in its CNC program"}}}
    ds = [_decision("deburring"), _decision("hole_machining"), _decision("cnc_routing")]
    rc._family_gate(ds, raw, {})
    assert [d.status for d in ds] == [rc.NOT_APPLICABLE, rc.NOT_APPLICABLE, rc.REQUIRED]
    assert "not deburred" in ds[0].reason and "CNC program" in ds[1].reason


def test_a_board_with_no_ruling_keeps_its_drilling():
    raw = {"P1": {"part_number": "P1", "normalized_material": "MDF", "description": "PANEL"}}
    ds = [_decision("hole_machining")]
    rc._family_gate(ds, raw, {})
    assert ds[0].status == rc.REQUIRED


def test_a_steel_part_is_not_touched_by_the_board_rule():
    raw = {"P1": {"part_number": "P1", "normalized_material": "MILD STEEL", "description": "PLATE",
                  "operations_ruled_out": {"deburring": "x"}}}
    ds = [_decision("deburring")]
    rc._family_gate(ds, raw, {})
    assert ds[0].status == rc.REQUIRED
