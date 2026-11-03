"""A part cut from section stock is cut once, and not lasered again (D-653).

12684-02-GA, 3 Nov 2026 (SCRUM-100/107/155). M06, a 1/2" square tube frame, carried a tube_cut
and a generic laser_cutting decision; the workbook remaps a laser on a tube to the Tube
department, so the book held two identical Tube rows for one cut. M07, 10 mm square bar, carried
Laser (Metal) and Saw. Neither record had a profile the compiler's tube rule reads, nor TUBE in
its name, and the stock-form gate rules a laser out on wire only — on a tube the cut is
redirected, not removed.

The rule: where a part's own record says it is cut from tube, bar or rod stock — its stock form,
the read's material family, its section, or its own printed material words — and a saw or tube
cut is already required on it, the sheet-laser decision is the same cut again and is ruled
NOT APPLICABLE, with the reason, never deleted. A measured flat is a profiled plate and keeps
its laser; a section nothing else cuts keeps the only cut it has.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402
import route_compiler as rc  # noqa: E402


def _decisions(part):
    graph = rc.compile_job_route([part], {})
    out = {}
    for d in graph.get("decisions") or []:
        d = d if isinstance(d, dict) else d.__dict__
        out[d["operation"]] = d
    return out


def _part(pn, ops, **extra):
    return dict({"part_number": pn, "description": "FRAME PART", "quantity": 1,
                 "normalized_material": "MILD_STEEL", "textual_operations": list(ops)}, **extra)


@pytest.mark.parametrize("evidence", [
    {"material_family": "tube"},
    {"stock_form": "tube"},
    {"material_text_as_printed": '1/2" SQUARE STEEL TUBE'},
    {"material_text_as_printed": "10mm SQUARE STEEL BAR"},
    {"section_stock": {"a": 25.0, "b": 25.0, "t": 1.5, "length_mm": 600.0}},
    {"material_family": "wire"},
])
@pytest.mark.parametrize("cut", ["saw", "tube_cut"])
def test_a_stock_part_already_cut_to_length_is_not_lasered_as_well(evidence, cut):
    d = _decisions(_part("J-01", ["laser_cutting", cut], **evidence))
    assert d[cut]["status"] == rc.REQUIRED, "the cut itself stands"
    assert d["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    assert "a second time" in d["laser_cutting"]["reason"] or \
        "cut from a stock length" in d["laser_cutting"]["reason"] or \
        "cut by the tube process" in d["laser_cutting"]["reason"]


def test_the_reason_names_the_stock_its_own_words_state():
    d = _decisions(_part("J-07", ["laser_cutting", "saw"],
                         material_text_as_printed="10mm SQUARE STEEL BAR"))
    reason = d["laser_cutting"]["reason"]
    assert "10 x 10 square bar" in reason and "'10mm SQUARE STEEL BAR'" in reason
    assert "a second time" in reason


def test_a_stock_part_nothing_else_cuts_keeps_its_only_cut():
    """2085's lesson: deleting the laser on a tube nobody saws makes the cut free. The rule
    needs the other cut; without it the laser is the cut, remapped to the Tube row."""
    sawn = _decisions(_part("J-02", ["laser_cutting", "tube_cut"], material_family="tube"))
    alone = _decisions(_part("J-02", ["laser_cutting"], material_family="tube"))
    assert sawn["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    assert alone["laser_cutting"]["status"] == rc.REQUIRED


def test_a_cut_a_ruling_has_taken_off_is_not_the_cut():
    """The other cut has to stand: a saw ruled off leaves the laser as the only cut."""
    ops = ["laser_cutting", "saw"]
    sawn = _decisions(_part("J-06", ops, material_family="tube"))
    ruled = _decisions(_part("J-06", ops, material_family="tube",
                             operations_ruled_out={"saw": "ruled off by the estimator"},
                             operation_ruling_sources={"saw": "estimator"}))
    assert sawn["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    assert ruled["saw"]["status"] == rc.RULED_OUT
    assert ruled["laser_cutting"]["status"] == rc.REQUIRED


def test_a_measured_flat_is_a_profiled_plate_and_keeps_its_laser():
    ops = ["laser_cutting", "saw"]
    unmeasured = _decisions(_part("J-03", ops, stock_form="tube"))
    measured = _decisions(_part("J-03", ops, stock_form="tube", dxf_augmented=True,
                                geometry_source="dxf_flat_pattern"))
    assert unmeasured["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    assert measured["laser_cutting"]["status"] == rc.REQUIRED


def test_a_sheet_part_with_a_saw_keeps_its_laser():
    """The rule reads the part's own stock evidence, never the saw alone."""
    sheet = _decisions(_part("J-04", ["laser_cutting", "saw"],
                             material_text_as_printed="MILD STEEL 3MM"))
    bar = _decisions(_part("J-04", ["laser_cutting", "saw"],
                           material_text_as_printed="10mm SQUARE STEEL BAR"))
    assert sheet["laser_cutting"]["status"] == rc.REQUIRED
    assert bar["laser_cutting"]["status"] == rc.NOT_APPLICABLE


def test_the_ruled_out_laser_stays_in_the_record():
    graph = rc.compile_job_route([_part("J-05", ["laser_cutting", "tube_cut"],
                                        material_family="tube")], {})
    lasers = [d if isinstance(d, dict) else d.__dict__ for d in graph["decisions"]]
    lasers = [d for d in lasers if d["operation"] == "laser_cutting"]
    assert len(lasers) == 1 and lasers[0]["status"] == rc.NOT_APPLICABLE, \
        "ruled out with its reason, never deleted"


# ── the whole chain on the 12684-02 parts ───────────────────────────────────────────────

@pytest.fixture
def _no_catalogue(monkeypatch):
    monkeypatch.setattr(E, "_lookup_catalogue_tube_price", lambda *a, **k: None)
    monkeypatch.setattr(E, "_lookup_catalogue_section_stock_rate", lambda *a, **k: None)


def test_the_outer_frame_is_cut_once_on_the_tube_cut_its_route_names(_no_catalogue):
    part = _part("12684-02-M06", ["laser_cutting", "tube_cut", "welding"],
                 description="OUTER FRAME", material_text_as_printed='1/2" SQUARE STEEL TUBE',
                 overall_length_mm=1500.0, overall_width_mm=500.0, weights=["0.58KG"])
    est = E.estimate_part(part, job_quantity=1)
    costs = (est.get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "saw" not in costs, "the tube cut its route names is the cut; no saw beside it"
    assert "Cut to length on the tube cut" in part["section_costing_adjustment"]["note"]
    d = _decisions(part)
    assert d["tube_cut"]["status"] == rc.REQUIRED
    assert d["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    cuts = [op for op, x in d.items() if op in ("tube_cut", "saw", "laser_cutting", "guillotine")
            and x["status"] == rc.REQUIRED]
    assert cuts == ["tube_cut"], cuts


def test_the_cross_bar_is_sawn_once_and_not_lasered(_no_catalogue):
    part = _part("12684-02-M07", ["laser_cutting", "saw"], description="CROSS BAR",
                 quantity=11, material_text_as_printed="10mm SQUARE STEEL BAR",
                 normalized_thickness_mm=10.0, overall_length_mm=484.6, overall_width_mm=10.0,
                 weights=["0.37KG"])
    E.estimate_part(part, job_quantity=1)
    d = _decisions(part)
    assert d["saw"]["status"] == rc.REQUIRED
    assert d["laser_cutting"]["status"] == rc.NOT_APPLICABLE


def test_the_arm_read_as_round_bar_is_not_lasered(_no_catalogue):
    part = _part("12684-02-M02", ["laser_cutting"], description="ARM", quantity=33,
                 hole_sizes_mm=["5"], overall_length_mm=153.1, weights=["0.02KG"])
    E.estimate_part(part, job_quantity=1)
    d = _decisions(part)
    assert d["laser_cutting"]["status"] == rc.NOT_APPLICABLE
    assert "wire" in d["laser_cutting"]["reason"]
    assert d["saw"]["status"] == rc.REQUIRED, "a bar cut from stock is cut (D-586)"
