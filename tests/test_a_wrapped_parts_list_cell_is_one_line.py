"""A wrapped parts-list cell read two ways is one line, not two (D-435).

8188-08-SA03's table prints the insert's code cell wrapped: "FIXING M6x12mm" over "THREADED
INSERT, HEADED HEX DRIVE". One reader took the first line as the code and the rest as the
description; another took the whole cell as the identity. The 17:37 book carried both, each
x4 — the drawing's four inserts charged as eight, £0.42 and £0.92.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402

_CODED = {"part_number": "FIXING M6X12MM", "description": "THREADED INSERT, HEADED HEX DRIVE",
          "quantity": 4, "page_roles": ["bought_in"]}
_WHOLE = {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "quantity": 4,
          "page_roles": ["bought_in"]}


def test_the_whole_cell_identity_folds_onto_the_coded_one():
    raw = {"FIXING M6X12MM": _CODED, "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE": _WHOLE}
    aliases = rc._raw_identity_aliases(raw, {})
    assert aliases == {"FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE": "FIXING M6X12MM"}


def test_across_the_two_sources_too():
    aliases = rc._raw_identity_aliases(
        {"FIXING M6X12MM": dict(_CODED)},
        {"FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE": dict(_WHOLE)})
    assert aliases.get("FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE") == "FIXING M6X12MM"


def test_a_disagreeing_count_keeps_both_for_a_person():
    raw = {"FIXING M6X12MM": _CODED,
           "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE": dict(_WHOLE, quantity=2)}
    assert rc._raw_identity_aliases(raw, {}) == {}


def test_a_different_row_is_not_folded():
    raw = {"FIXING M6X12MM": _CODED,
           "FIXING M6X12MM FLANGE BUTTON HEAD SCREW": dict(_WHOLE,
               part_number="FIXING M6X12MM FLANGE BUTTON HEAD SCREW")}
    assert rc._raw_identity_aliases(raw, {}) == {}


def test_the_graph_charges_the_insert_once_at_four():
    parts = [
        {"part_number": "8188-08-SA03", "description": "TIMBER SIGNAGE", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        dict(_CODED), dict(_WHOLE),
    ]
    extract = {"assemblies": [{"part_number": "8188-08-SA03", "children": [
        {"part_number": "FIXING M6X12MM", "qty": 4},
        {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "qty": 4}]}]}
    g = rc.build_part_graph(parts, extract, declared_product="8188-08-SA03")
    q = g["quantities"]
    assert q.get("FIXING M6X12MM") == 4, q
    assert "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE" not in q, q
