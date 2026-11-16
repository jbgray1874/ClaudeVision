"""12633-00 22:16 book: 12633-03-01P is two front panels per choc holder. Its Laser row read
H=2 at 336/hr — two pieces over ONE piece's run time — so the sheet charged one piece.

The engine's run_hours_per_unit is one piece's time. A row's throughput is its piece count
over its hours, so each part's time enters those hours once per piece it has.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate as wbp                                                  # noqa: E402


def _groups(parts):
    payload = {"nodes": [], "decisions": [
        {"decision_id": f"d{i}", "operation": "diamond_polish", "target_id": pn,
         "participants": [pn], "status": "required", "scope": "part", "sequence": 30,
         "qty_per_unit": q}
        for i, (pn, q, _h) in enumerate(parts)]}
    summary = {"estimate_summary": {"canonical_route_shadow": payload}}
    estimates = [{"part_number": pn, "normalized_material": "ACRYLIC",
                  "normalized_thickness_mm": 5.0,
                  "labour_estimate": {"run_hours_per_unit": {"diamond_polish": h},
                                      "batch_hours": {"diamond_polish": h * q + 0.1}}}
                 for pn, q, h in parts]
    return list(wbp.canonical_labour_groups(summary, estimates, 1).values())


def test_a_two_off_part_carries_two_pieces_of_time():
    [g] = _groups([("12633-03-01P", 2, 0.01)])
    assert g["qty"] == 2
    assert abs(g["run_hours_per_unit"] - 0.02) < 1e-9
    # so the row's throughput is one piece per 0.01 h, whatever the count
    assert abs(g["qty"] / g["run_hours_per_unit"] - 100.0) < 1e-6


def test_a_combined_row_weights_each_part_by_its_pieces():
    [g] = _groups([("12633-03-01P", 2, 0.01), ("12633-03-02P", 3, 0.02)])
    assert g["qty"] == 5
    assert abs(g["run_hours_per_unit"] - (2 * 0.01 + 3 * 0.02)) < 1e-9
