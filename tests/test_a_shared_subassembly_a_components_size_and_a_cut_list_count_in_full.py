"""A shared sub-assembly's descendants count under every parent, a component's size is not
the product's, and every piece of a cut list is coated (D-561, D-562, D-563).

The three gaps an independent review of 8a698c4 reproduced, generic in the engine and shown
here on a rail-shaped fixture.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as cl  # noqa: E402
import estimator as e  # noqa: E402
from bom_tree import resolve_effective_quantities  # noqa: E402


# ── D-561: a shared sub-assembly's descendants count under every parent ─────────────────

def _r(pn, parent, q):
    return {"part_number": pn, "source_pdf": parent, "bom_parent": parent, "quantity": q}


def _ga():
    """A GA that is one product: several codes at x1 beside the frame at x2 — not an
    arrangement of two (which the install-division rule would read a lone 'x2' as)."""
    return [_r("90001-01-01M", "90001-01-GA", 1), _r("90001-01-201", "90001-01-GA", 1),
            _r("90001-01-301", "90001-01-GA", 1), _r("90001-01-401", "90001-01-GA", 2),
            _r("FIXING125", "90001-01-GA", 6)]


def test_a_frame_under_two_parents_multiplies_its_members_by_both():
    rows = _ga() + [
        _r("90001-01-07M", "90001-01-401", 1), _r("90001-01-08M", "90001-01-401", 2),
        _r("90001-01-401", "90001-01-201", 1),             # the frame is used inside 201 as well
        _r("90001-01-03M", "90001-01-201", 1),
    ]
    eff = resolve_effective_quantities(rows, main_ga="90001-01-GA")["effective"]
    assert eff["90001-01-07M"] == 3 and eff["90001-01-08M"] == 6     # 2 on the GA + 1 inside 201


def test_a_single_parent_counts_as_before():
    rows = _ga() + [_r("90001-01-07M", "90001-01-401", 1), _r("90001-01-08M", "90001-01-401", 2)]
    eff = resolve_effective_quantities(rows, main_ga="90001-01-GA")["effective"]
    assert eff["90001-01-07M"] == 2 and eff["90001-01-08M"] == 4


def test_a_table_that_lists_a_code_twice_keeps_its_first_row():
    rows = _ga() + [_r("90001-01-401", "90001-01-GA", 5), _r("90001-01-07M", "90001-01-401", 1)]
    eff = resolve_effective_quantities(rows, main_ga="90001-01-GA")["effective"]
    assert eff["90001-01-07M"] == 2


# ── D-562: a component's size is not the product's ───────────────────────────────────────

def _parts():
    return [
        {"part_number": "90001-01-GA", "is_assembly_parent": True,
         "assembly_children": ["90001-01-401", "90001-01-05M"], "overall_size_mm": "1298 x 450 x 1438"},
        {"part_number": "90001-01-401", "is_assembly_parent": True, "owning_assembly": "90001-01-GA",
         "assembly_children": ["90001-01-08M"], "overall_size_mm": "803 x 354 x 60"},
        {"part_number": "90001-01-05M", "owning_assembly": "90001-01-GA", "overall_size_mm": "1154 x 497 x 2"},
        {"part_number": "90001-01-08M", "owning_assembly": "90001-01-401"},
    ]


def test_without_a_declared_product_the_one_root_is_the_product():
    parts = _parts()
    parts.reverse()                                        # the component is met first
    env = cl.product_envelope({}, parts)
    assert env and env["of"] == "90001-01-GA"
    assert (env["length"], env["width"], env["height"]) == (1438.0, 1298.0, 450.0)


def test_two_roots_or_none_name_no_product():
    parts = _parts()
    parts.append({"part_number": "90001-02-GA", "is_assembly_parent": True,
                  "assembly_children": ["90001-02-01M"], "overall_size_mm": "500 x 500 x 500"})
    assert cl.product_envelope({}, parts) is None
    assert cl.product_envelope({}, [{"part_number": "LOOSE", "overall_size_mm": "100 x 50 x 2"}]) is None
    assert cl._product_root([]) is None


def test_a_declared_product_still_wins_over_the_root_rule():
    env = cl.product_envelope({"declared_product": "90001-01-401"}, _parts())
    assert env and env["of"] == "90001-01-401" and env["length"] == 803.0


# ── D-563: every piece of a cut list is coated ───────────────────────────────────────────

def test_a_cut_list_is_coated_over_every_piece():
    one = e._section_outer_area_m2({"section_stock": {"a": 20, "b": 50, "t": 2, "profile_form": "RHS",
                                                      "length_mm": 703}})
    three = e._section_outer_area_m2({"section_stock": {"a": 20, "b": 50, "t": 2, "profile_form": "RHS",
                                                        "length_mm": 703,
                                                        "cut_lengths_mm": [703, 451, 451]}})
    assert one > 0
    assert abs(three - one * (703 + 451 + 451) / 703) < 1e-6


def test_a_section_without_a_cut_list_is_coated_over_its_length():
    a = e._section_outer_area_m2({"section_stock": {"a": 30, "b": 30, "t": 2, "profile_form": "SHS",
                                                    "length_mm": 1000}})
    assert abs(a - 4 * 0.030 * 1.0) < 1e-6              # 30 x 30 SHS: 120 mm perimeter x 1 m
