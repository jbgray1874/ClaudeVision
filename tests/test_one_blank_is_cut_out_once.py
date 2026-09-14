"""12349-02-69-06A, a 5 mm acrylic front cover, was charged a laser cut AND a routed cut.

    Laser (Acrylic) — 5mm HIGH IMPACT ACRYLIC (... , 12349-02-69-06A)   6 off
    CNC             — 5mm HIGH IMPACT ACRYLIC (12349-02-69-06A)         £6.81

Two ways of cutting one profile out of one sheet, both paid for. It is the kind of double
that survives a review because each line is individually plausible — a router line on an
acrylic part is not surprising, and neither is a laser line — and only reading them together
shows the blank being cut out twice.

THE CUT FILE HAD ALREADY ANSWERED IT. The DXF interpretation reads the layers and names a
recommended process; for 06A it says "router", and every run printed that on the console and
then costed the laser anyway, because nothing downstream consulted it.

So it is consulted. The named process keeps its op and the other comes off, out loud, naming
the file that settled it. Where the file names a combination or names nothing, BOTH STAY and
the line is flagged — a part can genuinely be profiled one way and pocketed another, and this
rule must not be the thing that decides that silently.

PER PART, WHICH IS THE WHOLE OF ITS SAFETY. An assembly carrying CNC while its own flats carry
the laser is the correct shape — 01A takes glue and routing, its seven flats take the laser —
and nothing here touches it, because neither of those parts carries both.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from estimator import estimate_process_times                            # noqa: E402


def _part(ops, process=None, **over):
    p = {"part_number": "12349-02-69-06A", "normalized_material": "ACRYLIC",
         "normalized_thickness_mm": 5.0, "textual_operations": list(ops),
         "dxf_source_file": "12349-02-69-06A_5MM_High Impact Acrylic_RevA.DXF"}
    if process is not None:
        p["dxf_interpretation"] = {"found": True, "recommended_process": process}
    p.update(over)
    return p


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the file names the process, and the other cut comes off ──────────────────────────────

def test_the_front_cover_is_routed_not_lasered():
    part = _part(["laser_cutting", "cnc_routing", "handling"], process="router")
    out = estimate_process_times(part)
    assert "laser_cutting" not in out["run_times_min_per_unit"]
    assert "cnc_routing" in out["run_times_min_per_unit"]
    assert "laser_cutting" in (part.get("removed_operations") or [])


def test_a_lasered_part_loses_the_router_instead():
    part = _part(["laser_cutting", "cnc_routing", "handling"], process="laser")
    out = estimate_process_times(part)
    assert "cnc_routing" not in out["run_times_min_per_unit"]
    assert "laser_cutting" in out["run_times_min_per_unit"]


def test_punch_counts_as_the_laser_side():
    part = _part(["punching", "cnc_routing"], process="punch")
    out = estimate_process_times(part)
    assert "cnc_routing" not in out["run_times_min_per_unit"]


def test_it_says_what_it_did_and_which_file_settled_it():
    part = _part(["laser_cutting", "cnc_routing"], process="router")
    estimate_process_times(part)
    f = _flags(part)
    assert "same profile paid for twice" in f
    assert "12349-02-69-06A_5MM_High Impact Acrylic_RevA.DXF" in f
    assert "'router'" in f
    assert "both go back on" in f


# ── where the evidence does not settle it, nothing is removed ────────────────────────────

def test_a_combination_keeps_both_and_asks():
    part = _part(["laser_cutting", "cnc_routing"], process="combination")
    out = estimate_process_times(part)
    assert "laser_cutting" in out["run_times_min_per_unit"]
    assert "cnc_routing" in out["run_times_min_per_unit"]
    assert "CUT TWICE?" in _flags(part)
    assert not part.get("removed_operations")


def test_no_interpretation_at_all_keeps_both_and_asks():
    part = _part(["laser_cutting", "cnc_routing"])
    estimate_process_times(part)
    assert "CUT TWICE?" in _flags(part)
    assert "no single process" in _flags(part)
    assert not part.get("removed_operations")


def test_an_unknown_process_keeps_both():
    part = _part(["laser_cutting", "cnc_routing"], process="unknown")
    estimate_process_times(part)
    assert not part.get("removed_operations")


# ── one cutting op, or none, is untouched ────────────────────────────────────────────────

def test_a_part_with_one_cut_is_untouched():
    for ops in (["laser_cutting", "folding"], ["cnc_routing", "handling"], ["handling"]):
        part = _part(ops, process="router")
        estimate_process_times(part)
        assert not part.get("removed_operations"), ops
        assert "CUT TWICE" not in _flags(part), ops


def test_the_acrylic_arrangement_and_its_flats_are_both_left_alone():
    """01A takes glue and routing; its flats take the laser. Two parts, one cut each — the
    shape that is CORRECT, and the one a rule like this could most easily break."""
    parent = {"part_number": "12349-02-69-01A", "normalized_material": "ACRYLIC",
              "normalized_thickness_mm": 5.0,
              "textual_operations": ["cnc_routing", "glue", "assembly"],
              "is_assembly_parent": True}
    estimate_process_times(parent)
    assert not parent.get("removed_operations")

    for n in range(1, 8):
        flat = {"part_number": f"12349-02-69-01A-0{n}", "normalized_material": "HIGH_IMPACT_ACRYLIC",
                "normalized_thickness_mm": 5.0,
                "textual_operations": ["laser_cutting", "manual_labour_acrylic"]}
        estimate_process_times(flat)
        assert not flat.get("removed_operations"), n


def test_the_steel_parts_of_this_job_are_untouched():
    """03M and 04M are lasered and folded. Nothing here can reach them."""
    for pn, g in (("12349-02-69-03M-01", 1.5), ("12349-02-69-03M-02", 1.5),
                  ("12349-02-69-04M", 1.2)):
        part = {"part_number": pn, "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g,
                "textual_operations": ["laser_cutting", "folding", "handling"]}
        estimate_process_times(part)
        assert not part.get("removed_operations"), pn
        assert "CUT TWICE" not in _flags(part), pn


def test_the_mdf_packer_keeps_its_joinery():
    """08J is routed and only routed. A rule about double cutting must not take its one cut
    away because 'cnc_joinery' is in the router family."""
    part = {"part_number": "12349-02-69-08J", "normalized_material": "MDF",
            "normalized_thickness_mm": 6.0,
            "textual_operations": ["cnc_routing", "wet_spray", "handling"]}
    out = estimate_process_times(part)
    assert "cnc_routing" in out["run_times_min_per_unit"]
    assert not part.get("removed_operations")
