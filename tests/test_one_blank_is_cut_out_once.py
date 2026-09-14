"""12349-02-69-06A, a 5 mm acrylic front cover, was charged a laser cut AND a routed cut.

    Laser (Acrylic) — 5mm HIGH IMPACT ACRYLIC (... , 12349-02-69-06A)   6 off
    CNC             — 5mm HIGH IMPACT ACRYLIC (12349-02-69-06A)         £6.81

Two ways of cutting one profile out of one sheet, both paid for. It is the kind of double
that survives review because each line is individually plausible — a router line on an acrylic
part is not surprising, and neither is a laser line — and only reading them together shows the
blank being cut out twice.

AND THE THING THAT LOOKED LIKE THE ANSWER WAS A COIN FLIP. This rule keyed on the DXF
interpreter's `recommended_process` for exactly one commit. The runner's own log refuted it:
the same unchanged file comes back

    06A: laser · laser · laser · router · laser · router · laser · router · router · laser

over ten runs. SDI's cut files cannot settle it either — the layer set is a fixed SolidWorks
export template (SLD-0, BENDLINES, ETCHING, RIB, C_SNK, HIDDEN, REBATE, LANCEFORM) and not one
layer names a machine. Keyed on that, the rule would have stripped the laser on some runs and
the router on others, on one pack: a visible double charge turned into an invisible coin flip,
which is worse than the double it replaced.

So the decision comes from config.CUT_METHOD_BY_MATERIAL — the shop's own practice, written
down once, the same on every run — or it is not made here at all. The table ships EMPTY, and an
absent rule flags the line for a person rather than picking a machine.

PER PART, WHICH IS THE WHOLE OF ITS SAFETY. An assembly carrying CNC while its own flats carry
the laser is the correct shape — 01A takes glue and routing, its seven flats take the laser —
and nothing here touches it, because neither of those parts carries both.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from estimator import estimate_process_times, _cut_method_rule          # noqa: E402


@pytest.fixture(autouse=True)
def _no_shop_rule(monkeypatch):
    """Empty, exactly as it ships. Every test that wants a rule asks for one."""
    monkeypatch.setattr(config, "CUT_METHOD_BY_MATERIAL", [])


def _rule(monkeypatch, method, material="ACRYLIC", max_mm=None):
    entry = {"material": material, "method": method}
    if max_mm is not None:
        entry["max_thickness_mm"] = max_mm
    monkeypatch.setattr(config, "CUT_METHOD_BY_MATERIAL", [entry])


def _part(ops, **over):
    p = {"part_number": "12349-02-69-06A", "normalized_material": "ACRYLIC",
         "normalized_thickness_mm": 5.0, "textual_operations": list(ops)}
    p.update(over)
    return p


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the shop's rule decides, and the other cut comes off ─────────────────────────────────

def test_the_front_cover_takes_one_cut_when_the_shop_has_a_rule(monkeypatch):
    _rule(monkeypatch, "router")
    part = _part(["laser_cutting", "cnc_routing", "handling"])
    out = estimate_process_times(part)
    assert "laser_cutting" not in out["run_times_min_per_unit"]
    assert "cnc_routing" in out["run_times_min_per_unit"]
    assert "laser_cutting" in (part.get("removed_operations") or [])


def test_a_lasered_material_loses_the_router_instead(monkeypatch):
    _rule(monkeypatch, "laser")
    part = _part(["laser_cutting", "cnc_routing", "handling"])
    out = estimate_process_times(part)
    assert "cnc_routing" not in out["run_times_min_per_unit"]
    assert "laser_cutting" in out["run_times_min_per_unit"]


def test_punch_counts_as_the_laser_side(monkeypatch):
    _rule(monkeypatch, "punch")
    part = _part(["punching", "cnc_routing"])
    out = estimate_process_times(part)
    assert "cnc_routing" not in out["run_times_min_per_unit"]


def test_it_says_what_it_did_and_whose_rule_settled_it(monkeypatch):
    _rule(monkeypatch, "router")
    part = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(part)
    f = _flags(part)
    assert "same profile paid for twice" in f
    assert "CUT_METHOD_BY_MATERIAL" in f and "'router'" in f
    assert "both go back on" in f


def test_a_gauge_bound_is_honoured(monkeypatch):
    """"Acrylic up to 8 mm is lasered" must not price a 20 mm block the same way."""
    _rule(monkeypatch, "laser", max_mm=8)
    thin = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(thin)
    assert thin.get("removed_operations")

    thick = _part(["laser_cutting", "cnc_routing"], normalized_thickness_mm=20.0)
    estimate_process_times(thick)
    assert not thick.get("removed_operations")
    assert "CUT TWICE?" in _flags(thick)


def test_another_materials_rule_does_not_reach_this_one(monkeypatch):
    _rule(monkeypatch, "router", material="MDF")
    part = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(part)
    assert not part.get("removed_operations")


# ── with no written rule, nothing is removed and nothing is guessed ──────────────────────

def test_an_empty_table_keeps_both_and_asks():
    part = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(part)
    assert "CUT TWICE?" in _flags(part)
    assert not part.get("removed_operations")


def test_it_says_why_it_could_not_decide():
    part = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(part)
    f = _flags(part)
    assert "name no process" in f
    assert "CUT_METHOD_BY_MATERIAL holds no rule" in f


def test_the_dxf_interpreters_guess_is_never_consulted(monkeypatch):
    """THE POINT OF THE WHOLE COMMIT. The same file returned laser on some runs and router on
    others; a costing decision taken from it is a coin flip with a price attached."""
    for guess in ("router", "laser", "punch", "combination", "unknown"):
        part = _part(["laser_cutting", "cnc_routing"],
                     dxf_interpretation={"found": True, "recommended_process": guess})
        estimate_process_times(part)
        assert not part.get("removed_operations"), guess
        assert "CUT TWICE?" in _flags(part), guess


def test_the_rule_reader_returns_nothing_rather_than_a_default():
    assert _cut_method_rule({"normalized_material": "ACRYLIC"}) == ""
    assert _cut_method_rule({}) == ""


# ── one cutting op, or none, is untouched ────────────────────────────────────────────────

def test_a_part_with_one_cut_is_untouched(monkeypatch):
    _rule(monkeypatch, "router")
    for ops in (["laser_cutting", "folding"], ["cnc_routing", "handling"], ["handling"]):
        part = _part(ops)
        estimate_process_times(part)
        assert not part.get("removed_operations"), ops
        assert "CUT TWICE" not in _flags(part), ops


def test_the_acrylic_arrangement_and_its_flats_are_both_left_alone(monkeypatch):
    """01A takes glue and routing; its flats take the laser. Two parts, one cut each — the
    shape that is CORRECT, and the one a rule like this could most easily break."""
    _rule(monkeypatch, "router")
    parent = {"part_number": "12349-02-69-01A", "normalized_material": "ACRYLIC",
              "normalized_thickness_mm": 5.0,
              "textual_operations": ["cnc_routing", "glue", "assembly"],
              "is_assembly_parent": True}
    estimate_process_times(parent)
    assert not parent.get("removed_operations")

    for n in range(1, 8):
        flat = {"part_number": f"12349-02-69-01A-0{n}",
                "normalized_material": "HIGH_IMPACT_ACRYLIC",
                "normalized_thickness_mm": 5.0,
                "textual_operations": ["laser_cutting", "manual_labour_acrylic"]}
        estimate_process_times(flat)
        assert not flat.get("removed_operations"), n


def test_the_steel_parts_of_this_job_are_untouched(monkeypatch):
    """03M and 04M are lasered and folded. Nothing here can reach them."""
    _rule(monkeypatch, "router", material="MILD_STEEL")
    for pn, g in (("12349-02-69-03M-01", 1.5), ("12349-02-69-03M-02", 1.5),
                  ("12349-02-69-04M", 1.2)):
        part = {"part_number": pn, "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g,
                "textual_operations": ["laser_cutting", "folding", "handling"]}
        estimate_process_times(part)
        assert not part.get("removed_operations"), pn
        assert "CUT TWICE" not in _flags(part), pn


def test_the_mdf_packer_keeps_its_joinery(monkeypatch):
    """08J is routed and only routed. A rule about double cutting must not take its one cut
    away because 'cnc_joinery' is in the router family."""
    _rule(monkeypatch, "laser", material="MDF")
    part = {"part_number": "12349-02-69-08J", "normalized_material": "MDF",
            "normalized_thickness_mm": 6.0,
            "textual_operations": ["cnc_routing", "wet_spray", "handling"]}
    out = estimate_process_times(part)
    assert "cnc_routing" in out["run_times_min_per_unit"]
    assert not part.get("removed_operations")


def test_the_table_ships_empty():
    """So no job's price can move because somebody added a rule they had not agreed."""
    assert config.CUT_METHOD_BY_MATERIAL == [] or all(
        isinstance(r, dict) and r.get("method") in ("laser", "punch", "router")
        for r in config.CUT_METHOD_BY_MATERIAL)
