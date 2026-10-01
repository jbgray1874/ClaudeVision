"""tools/check_book_against_brief.py reports EVERY pin of an estimator's brief against a run's
record (docs/briefs/<job>.facts.json). A review wants the whole list, not the first failure.
Synthetic records only: the checker must know nothing about any job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import check_book_against_brief as cb                                  # noqa: E402


def _line(pn, qty, ops=(), route=(), desc="", kind="leaf", charged=1.0):
    return {"part_number": pn, "qty_per_unit": qty, "operations": list(ops),
            "route_operations": list(route), "description": desc, "kind": kind,
            "charged_unit_gbp": charged}


LINES = [
    _line("A-GA", 1, ["powder_coating"], kind="assembly"),
    _line("A-01M", 16, ["laser_cutting"]),
    _line("A-02M", 2, ["laser_cutting", "folding"]),
    _line("A-03J", 1, kind="leaf", charged=None),
    _line("A-03J-01", 1, ["cnc_routing", "wet_spray"]),
    _line("FIXING-X16", 8, desc="3.5x16mm PAN HEAD"),
    _line("FIXING-X12", 16, desc="3.5x12mm PAN HEAD"),
    _line("BI-SCREW", 16, desc="3.5x12mm PAN HEAD"),
]
SUMMARY = {
    "estimate_summary": {
        "canonical_route_shadow": {"product_root": "A-GA"},
        "part_estimates": [
            {"part_number": "A-01M", "material_estimate": {"unit_material_mass_kg": 0.01}},
            {"part_number": "A-02M", "material_estimate": {"unit_material_mass_kg": 263.0}},
        ]},
    "set_aside_outside_product": [{"part_number": "B-GA"}],
}


def _run(facts, monkeypatch, xlsx=None):
    monkeypatch.setattr(cb, "_lines", lambda _s: LINES)
    return cb.check(SUMMARY, facts, xlsx)


def _by(res, check):
    return {item: ok for c, item, ok, _ in res.rows if c == check}


def test_every_pin_is_reported_not_just_the_first(monkeypatch):
    res = _run({"product_root": "A-GA", "not_set_aside": ["B-GA"],
                "quantities": {"A-01M": 16, "A-02M": 1}}, monkeypatch)
    assert _by(res, "product_root") == {"A-GA": True}
    assert _by(res, "not_set_aside") == {"B-GA": False}
    assert _by(res, "quantity") == {"A-01M": True, "A-02M": False}
    assert len(res.failed) == 2


def test_a_doubled_or_merged_line_fails_exactly_one_line(monkeypatch):
    res = _run({"exactly_one_line": {"X16MM PAN HEAD": 8, "X12MM PAN HEAD": 16}}, monkeypatch)
    assert _by(res, "exactly_one_line") == {"X16MM PAN HEAD": True, "X12MM PAN HEAD": False}


def test_routes_pieces_and_cut_assemblies(monkeypatch):
    res = _run({"required_operations": {"A-02M": ["folding"], "A-03J": ["wet_spray"]},
                "required_operations_incl_pieces": {"A-03J": ["wet_spray"]},
                "forbidden_operations": {"A-01M": ["folding", "laser_cutting"]},
                "no_cut_assemblies": True}, monkeypatch)
    assert _by(res, "required_op") == {"A-02M folding": True, "A-03J wet_spray": False,
                                       "A-03J (or its pieces) wet_spray": True}
    assert _by(res, "forbidden_op") == {"A-01M folding": True, "A-01M laser_cutting": False}
    assert _by(res, "no_cut_assemblies") == {"assemblies": True}


def test_a_title_block_mass_used_as_material_is_caught(monkeypatch):
    res = _run({"max_unit_material_mass_kg": {"A-02M": 2.0},
                "min_unit_material_mass_kg": {"A-01M": 0.001},
                "unit_mass_kg": {"expected": 1.0, "tolerance_pct": 35},
                "material_charged": ["A-01M", "A-03J"]}, monkeypatch)
    assert _by(res, "max_mass") == {"A-02M": False}
    assert _by(res, "min_mass") == {"A-01M": True}
    assert _by(res, "unit_mass") == {"1 kg": False}
    assert _by(res, "material_charged") == {"A-01M": True, "A-03J": False}


def test_the_breaks_are_read_off_the_book(tmp_path, monkeypatch):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quantity Breaks"
    ws.append(["Quantity breaks"])
    ws.append(["Quantity", 1, 10, 50])
    ws.append(["Unit cost £", 100.0, 50.0, 40.0])
    path = tmp_path / "book.xlsx"
    wb.save(path)
    assert _by(_run({"quantity_breaks": [1, 10, 50]}, monkeypatch, path),
               "quantity_breaks") == {"[1, 10, 50]": True}
    assert _by(_run({"quantity_breaks": [1, 10, 500]}, monkeypatch, path),
               "quantity_breaks") == {"[1, 10, 500]": False}
    assert _by(_run({"quantity_breaks": [1]}, monkeypatch), "quantity_breaks") == {"[1]": False}


def test_the_card_spinner_brief_is_well_formed():
    facts = json.loads((ROOT / "docs" / "briefs" / "12173-02.facts.json").read_text("utf-8"))
    assert facts["product_root"] == "12173-02-GA"
    assert facts["quantity_breaks"] == [1, 10, 50, 100, 200, 500]
    known = {"_reviewed", "_note", "product_root", "not_set_aside", "quantity_breaks",
             "quantities", "exactly_one_line", "required_operations",
             "required_operations_incl_pieces", "forbidden_operations",
             "forbidden_operations_anywhere", "material_charged", "no_cut_assemblies",
             "forbidden_names_everywhere", "unit_mass_kg", "max_unit_material_mass_kg",
             "min_unit_material_mass_kg"}
    assert set(facts) <= known, set(facts) - known


def test_the_checker_names_no_job():
    src = (ROOT / "tools" / "check_book_against_brief.py").read_text("utf-8")
    import re
    assert not re.search(r"\b\d{4,5}-\d{2}\b", src), "a job number in the generic checker"
