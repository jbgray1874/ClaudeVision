"""A bought-in item is fitted by the assembly it goes into, once (D-661).

12684-02-GA, every run on 3 Nov 2026: the four stick-on bumpers FIXING1270 were listed on the GA's
Assemble/pack row ("covers 12684-02-101SA, 12684-02-102SA, BI-UPC, FIXING1270") and charged again
on an Assemble/pack row of their own, 4 off with a 15 minute set-up: GBP 9.11 at 1 off at 18:11,
at a rate that moved from 90/hr to 20/hr to 58/hr between runs. A purchased item has nothing of
its own to put together; fitting it is work on the assembly that holds it.

The rule: a bought-in item's own assembly operation that nothing stronger than the engine's
inference raised stands down when an assembly above it charges assembly. One its sheet or the
BOM states stays, and an item with no charged assembly above it keeps its own.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402
from route_compiler import NOT_APPLICABLE, REQUIRED  # noqa: E402


def _graph():
    nodes = [SimpleNamespace(part_number="T-GA", kind="assembly"),
             SimpleNamespace(part_number="T-102SA", kind="assembly"),
             SimpleNamespace(part_number="FIXING1270", kind="bought_in"),
             SimpleNamespace(part_number="T-M04", kind="leaf")]
    return {"nodes": nodes,
            "children": {"T-GA": {"T-102SA": 1, "FIXING1270": 4}, "T-102SA": {"T-M04": 1}}}


def _fit(did, target, source, qty=1.0, participants=None):
    return SimpleNamespace(decision_id=did, operation="assembly", status=REQUIRED,
                           target_id=target, source=source, qty_per_unit=qty,
                           participants=participants or [target], reason="",
                           field_provenance={})


def test_the_bumpers_own_inferred_fitting_stands_down_under_the_gas_assembly():
    ga = _fit("d-ga", "T-GA", "bom_tree", participants=["FIXING1270", "T-102SA"])
    own = _fit("d-bump", "FIXING1270", "inference", qty=4.0)
    issues = []
    assert rc._bought_in_fitted_by_its_assembly([ga, own], _graph(), issues) == ["FIXING1270"]
    assert own.status == NOT_APPLICABLE and "fitted as part of T-GA" in own.reason
    assert own.field_provenance["status"] == "bought_in_fitted_by_its_assembly"
    assert ga.status == REQUIRED, "the assembly's own row is untouched"
    assert issues and issues[0]["fitted_by"] == "T-GA"


def test_a_fitting_its_sheet_or_bom_states_is_kept():
    ga = _fit("d-ga", "T-GA", "bom_tree")
    own = _fit("d-bump", "FIXING1270", "drawing_deterministic", qty=4.0)
    assert rc._bought_in_fitted_by_its_assembly([ga, own], _graph()) == []
    assert own.status == REQUIRED


def test_with_no_charged_assembly_above_it_the_item_keeps_its_fitting():
    own = _fit("d-bump", "FIXING1270", "inference", qty=4.0)
    assert rc._bought_in_fitted_by_its_assembly([own], _graph()) == []
    assert own.status == REQUIRED


def test_a_made_part_is_not_touched():
    ga = _fit("d-ga", "T-GA", "bom_tree")
    plate = _fit("d-m04", "T-M04", "inference")
    assert rc._bought_in_fitted_by_its_assembly([ga, plate], _graph()) == []
    assert plate.status == REQUIRED
