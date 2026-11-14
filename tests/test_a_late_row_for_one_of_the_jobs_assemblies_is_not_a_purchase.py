"""A late table row for one of the job's own assemblies is not priced as a purchase.

11896-02-01-GA, 14 Nov 2026. SA01 and SA02 are wall panel sub-assemblies: a board panel and
three Z-bars each, every member charged. The table reader added a row for each after costing.
Those late rows knew nothing of the members, wore the table's bought-in role, and were priced
as purchases: £10.00 each, £11.04 with handling, on top of their own members.

The codes and prices here are this test's own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E  # noqa: E402

SA, PANEL, BAR = "T-02-SA01", "T-02-01J", "T-02-02M"


def _summary(late_code=SA, writeup_children=(PANEL, BAR)):
    asm = {"part_number": SA, "description": "WALL MOUNT PANEL - GA", "is_sub_assembly": True}
    if writeup_children:
        asm.update(assembly_children=list(writeup_children), is_assembly_parent=True)
    return {
        "quantity": 1,
        "manufacturing_writeup": {"parts": [
            asm, {"part_number": PANEL, "description": "WALL PANEL"},
            {"part_number": BAR, "description": "Z-BAR"}]},
        "estimate_summary": {"part_estimates": [
            {"part_number": late_code, "description": "WALL MOUNT PANEL - GA", "quantity": 1,
             "page_roles": ["bought_in"], "is_bought_in": True,
             "review_flags": ["Added from dual-path BOM table read"]}]},
    }


@pytest.fixture()
def priced(monkeypatch):
    """Every purchase lookup answers £10.00, as the catalogue did for these rows."""
    asked = []

    def _answer(part):
        asked.append(str(part.get("part_number")))
        return {"applied_unit_cost": 10.0, "applied": True,
                "result": {"selected": {"source": "catalogue", "price": 10.0}}}

    monkeypatch.setattr(E, "_resolve_part_system_cost", _answer)
    monkeypatch.setenv("SDI_OFFLINE", "1")
    return asked


def _line(summary):
    E.cost_uncosted_bought_in_records(summary)
    return summary["estimate_summary"]["part_estimates"][0]


def _material_money(pe):
    me = pe.get("material_estimate") or {}
    return float(me.get("unit_material_cost_gbp") or 0.0)


def test_a_late_row_for_an_assembly_of_the_job_takes_no_purchase_price(priced):
    pe = _line(_summary())
    assert _material_money(pe) == 0.0, pe.get("material_estimate")
    assert (pe.get("material_estimate") or {}).get("cost_method") != "bought_in_unit_price"
    assert pe.get("assembly_children") == [PANEL, BAR] and pe.get("is_assembly_parent") is True
    assert "bought_in" not in (pe.get("page_roles") or [])
    assert any("assembly of this job's own parts" in f and PANEL in f for f in pe["review_flags"])


def test_a_late_row_for_a_real_purchase_is_still_priced(priced):
    """Contrast: the same row under a code that is not one of the job's assemblies."""
    pe = _line(_summary(late_code="FIXING-T99"))
    assert _material_money(pe) == 10.0, pe.get("material_estimate")
    assert pe.get("assembly_children") in (None, [])


def test_an_assembly_code_the_writeup_gives_no_members_for_is_left_as_the_table_read_it(priced):
    """Contrast: nothing says what it is made of, so nothing is taken from it."""
    pe = _line(_summary(writeup_children=()))
    assert not pe.get("assembly_children")
    assert not any("assembly of this job's own parts" in f for f in pe["review_flags"])
