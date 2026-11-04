"""Pieces of one board share a program; a plating note quotes the weldment's finish (D-695).

12693-01-GA's 19:40 book (build 43c8ec7), after D-688 split 12693-01-04J into its pieces:

  * The two 12 mm strips, 1145 x 210 x2 and 725 x 210 x1, each chose the stock size that
    suited it, 2440 x 1220 and 3050 x 1525, and the one-set-up proof refused them because
    they sat on "DIFFERENT stock sheets". Both fit either sheet: the order takes 0.27 of a
    2440 x 1220 or 0.21 of a 3050 x 1525. Each kept a full 15-minute CNC set-up.
  * The plating line quoted the finish as "LIGHT AGED ZINC PLATED WITH WAXED SEE WELDMENT
    REFER TO SUB ASSEMBLY": the weldment's finish with its members' pointers run on.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from wb_populate import _common_stock_sheet  # noqa: E402


def _pe(pn, length, width, sheet, t=12.0):
    return {"part_number": pn, "normalized_material": "MDF", "normalized_thickness_mm": t,
            "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width},
            "blank_length_mm": length, "blank_width_mm": width,
            "material_estimate": {"stock_estimate": {"candidate_sheet_size_mm": list(sheet)}}}


def _group(pn, qty):
    return {"parts": [pn], "qty": qty}


def test_two_strips_on_two_stock_sizes_share_the_sheet_that_takes_the_least():
    est = {"P-02": _pe("P-02", 1145, 210, (2440, 1220)),
           "P-03": _pe("P-03", 725, 210, (3050, 1525))}
    got = _common_stock_sheet([_group("P-02", 2), _group("P-03", 1)], est, 1)
    assert got is not None
    sheet, frac = got
    assert sheet == (3050, 1525)
    assert frac == pytest.approx(2 / 12 + 1 / 24)


def test_a_member_that_fits_no_shared_sheet_proves_nothing():
    """Neither sheet holds the other's part: 1200 wide is past a 1100 sheet, 2700 long is
    past a 2440 one."""
    est = {"P-02": _pe("P-02", 2400, 1200, (2440, 1220)),
           "P-09": _pe("P-09", 2700, 1000, (2800, 1100))}
    assert _common_stock_sheet([_group("P-02", 1), _group("P-09", 1)], est, 1) is None


def test_a_member_with_no_blank_is_not_guessed():
    est = {"P-02": _pe("P-02", 1145, 210, (2440, 1220)),
           "P-03": {"part_number": "P-03"}}
    assert _common_stock_sheet([_group("P-02", 1), _group("P-03", 1)], est, 1) is None


def test_the_proof_uses_the_common_sheet():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    i = src.index("ONE STOCK SHEET THEY CAN ALL BE CUT FROM IS ONE PROGRAM (D-695)")
    block = src[i:i + 1800]
    assert "_common_stock_sheet(_members, estimates, order_qty)" in block
    assert "re-nested together on one" in block


def _plated(member_finishes):
    from estimator import apply_subcontract_plating
    parts = [{"part_number": "12999-01-104", "description": "WORKTOP WELDMENT",
              "normalized_finish": "LIGHT AGED ZINC PLATED WITH WAXED",
              "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 18.3}}]
    for pn, fin in member_finishes.items():
        parts.append({"part_number": pn, "description": "MEMBER", "normalized_finish": fin,
                      "quantity": 1, "material_estimate": {"unit_material_mass_kg": 0.5}})
    parts.append({"part_number": "12999-01-104-PLATE", "_plating_placeholder": True,
                  "_plating_weldment": "12999-01-104",
                  "_plating_members": ["12999-01-104"] + list(member_finishes),
                  "quantity": 1, "description": "plating"})
    apply_subcontract_plating(parts, {"customer": "Test"}, 1, parts)
    return parts[-1]


def test_member_pointers_are_not_quoted_as_the_finish():
    line = _plated({"12999-01-03M": "SEE WELDMENT", "12999-01-05M": "REFER TO SUB ASSEMBLY"})
    note = " ".join(str(f) for f in line.get("review_flags") or [])
    assert "'LIGHT AGED ZINC PLATED WITH WAXED'" in note
    assert "SEE WELDMENT" not in note.split("plated members")[0]
    assert line["material_estimate"]["cost_method"] == "subcontract_plating_quote_needed"
