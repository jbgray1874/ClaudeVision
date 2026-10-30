"""12173-02 Card Spinner, 1 Oct 2026 (D-377): "how can we be welding MDF? or mixing MDF with
acrylic" — James Gray.

12173-03-03J, an MFC (melamine faced chipboard) back panel, was charged Weld (CO2) and Dress
Welds: the no-weld gate held an exact list of board names that did not include MFC, so the
pack's general weld note landed on it while the two MDF panels beside it were cleared. And
the MDF and MFC panels were charged "Drill (Acrylic)" and "Manual labour (Acrylic)" deburring
beside the CNC Joinery row that already cuts them — the joinery department map had no entry
for drilling or deburring, so both fell through to the acrylic bench.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf                                     # noqa: E402
import estimator                                              # noqa: E402
import wb_populate as wb                                      # noqa: E402


def _panel(material, ops):
    return {"part_number": "X-03J", "description": "BACK PANEL", "quantity": 1,
            "normalized_material": material, "normalized_thickness_mm": 18.0,
            "blank_length_mm": 600, "blank_width_mm": 400,
            "textual_operations": list(ops), "operations": list(ops)}


def _ops(part):
    pt = estimator.estimate_process_times(part)
    return set((pt.get("run_times_min_per_unit") or {}).keys()) | \
        set((pt.get("setup_times_min") or {}).keys())


def test_the_board_test_knows_mfc_and_never_calls_metal_board():
    for m in ("MFC", "MELAMINE FACED CHIPBOARD", "MDF", "25mm MDF", "PLYWOOD", "OSB"):
        assert cf.is_timber_board(m), m
    for m in ("MILD STEEL", "STAINLESS STEEL", "ALUMINIUM", "ACRYLIC", "", None):
        assert not cf.is_timber_board(m), m


def test_an_mfc_panel_is_not_welded_or_dressed():
    got = _ops(_panel("MFC", ["cnc_routing", "welding"]))
    assert "welding" not in got and "dress_welds" not in got
    assert "cnc_routing" in got


def test_a_routed_board_is_not_drilled_or_deburred_separately():
    part = _panel("MDF", ["cnc_routing", "hole_machining", "deburring"])
    got = _ops(part)
    assert "hole_machining" not in got and "deburring" not in got
    assert "cnc_routing" in got
    assert "hole_machining" in part["operations_ruled_out"]
    assert "deburring" in part["operations_ruled_out"]


def test_a_sawn_board_keeps_its_drilling_on_the_joinery_machines():
    part = _panel("PLYWOOD", ["saw", "hole_machining"])
    assert "hole_machining" in _ops(part)
    assert wb._map_operation("hole_machining", True, material="PLYWOOD") == "Machines Joinery"


def test_board_is_never_sent_to_an_acrylic_department():
    for op in ("hole_machining", "drilling", "deburring"):
        assert "Acrylic" not in wb._map_operation(op, True, material="MDF"), op
    # acrylic itself keeps its own bench
    assert wb._map_operation("hole_machining", True, material="ACRYLIC") == "Drill (Acrylic)"


def test_steel_is_untouched():
    got = _ops({**_panel("MILD STEEL", ["laser_cutting", "welding"]), "normalized_thickness_mm": 2.0})
    assert "welding" in got
