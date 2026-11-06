"""One length is cut once, by one process (D-730).

12677-01-01M RISER FRAME, 6 Nov 2026 10:38 book: its own record sawed its twelve 10 x 10 x 1.2
tube pieces (12 cuts at the saw's per-cut allowance, a Saw row) and the extract inferred a tube
cut from the same cut list (a Tube row). One set of cuts was charged twice. Where two different
cut-to-length operations are both required on one part, the better-evidenced one stands and the
other is ruled not applicable, its reading kept as evidence. Synthetic records.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                              # noqa: E402

TUBE_CUT = {"operation": "tube_cut", "part_numbers": ["R-01M"], "scope": "part",
            "inferred": True}


def _cuts(routes, own_ops):
    parts = [{"part_number": "R-GA", "is_assembly_parent": True,
              "assembly_children": ["R-01M"]},
             {"part_number": "R-01M", "description": "RISER FRAME",
              "normalized_material": "MILD STEEL", "textual_operations": list(own_ops),
              "operation_sources": {o: "drawing_deterministic" for o in own_ops},
              "section_stock": {"a": 10, "b": 10, "t": 1.2, "profile_form": "SHS",
                                "cut_lengths_mm": [299] * 8 + [80] * 4}}]
    job = {"top_assembly": {"part_number": "R-GA"},
           "assemblies": [{"part_number": "R-GA",
                           "children": [{"part_number": "R-01M", "qty": 1}]}],
           "routes": list(routes)}
    out = rc.compile_job_route(parts, job, known_assemblies=["R-GA"])
    return {d["operation"]: d for d in out["decisions"]
            if d["target_id"] == "R-01M" and d["operation"] in ("saw", "tube_cut")}


def test_a_saw_and_an_inferred_tube_cut_on_one_part_charge_one_cut():
    cuts = _cuts([TUBE_CUT], ["saw"])
    assert cuts["saw"]["status"] == "required"
    assert cuts["tube_cut"]["status"] == "not_applicable"
    assert "already cut to length by its saw" in cuts["tube_cut"]["reason"]


def test_a_saw_alone_stands():
    assert _cuts([], ["saw"])["saw"]["status"] == "required"


def test_a_tube_cut_alone_stands():
    assert _cuts([TUBE_CUT], [])["tube_cut"]["status"] == "required"


def test_the_ruling_is_on_the_record_not_a_vanished_line():
    """The tube-cut reading stays as a decision, ruled out with its reason, so the record
    shows it was read and why it is not charged."""
    cuts = _cuts([TUBE_CUT], ["saw"])
    assert "tube_cut" in cuts and cuts["tube_cut"]["reason"]
