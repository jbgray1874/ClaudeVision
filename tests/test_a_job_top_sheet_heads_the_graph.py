"""12645 run of 28 Sep 2026: "[bom] 5 row(s) name an owner this job does not recognise ...
12645 - DRS EXTERNAL SHELTER V2" and "DECLARED PRODUCT '12645' NOT RESOLVED ... roll-up
STOPPED". The shelter sheet is filed "12645 - DRS External Shelter V2_REVA.PDF" and numbered
"12645 - DRS EXTERNAL SHELTER V2": not a hyphenated drawing number, so it was never one of the
job's drawings and its table's rows had no owner (D-312)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402

FILES = {"job_source_pdfs": ["12645 - DRS External Shelter V2_REVA.PDF", "12645-01GA V2_REVA.PDF",
                             "12645-02GA_REVA.pdf", "12645-03GA_REVA.pdf"]}
_TOP = "12645 - DRS EXTERNAL SHELTER V2"


def _graph():
    parts = [{"part_number": p, "description": d, "quantity": q} for p, d, q in [
        ("12645-01GA", "BODY FRAME", 1), ("12645-02GA", "DOOR FRAME", 1), ("12645-03GA", "DOOR", 1),
        ("12645-01-01M", "BACK PANEL", 3), ("12645-02-01M", "Heel post", 2),
        ("12645-03-01M", "Door panel", 1), ("ROLLER SHUTTER", "Roller Shutter Door", 2)]]
    bom = [{"part_number": "12645-01GA V2", "parent": _TOP, "qty": 1},
           {"part_number": "12645-02GA", "parent": _TOP, "qty": 1},
           {"part_number": "12645-03GA", "parent": _TOP, "qty": 1},
           {"part_number": "Roller Shutter", "parent": _TOP, "qty": 2},
           {"part_number": "12645-01-01M", "parent": "12645-01GA", "qty": 3},
           {"part_number": "12645-02-01M", "parent": "12645-02GA", "qty": 2},
           {"part_number": "12645-03-01M", "parent": "12645-03GA", "qty": 1}]
    return rc.build_part_graph(parts, bom_rows=bom,
                               known_assemblies=rc.job_drawing_numbers(FILES),
                               declared_product="12645")


def test_the_top_sheet_is_one_of_the_jobs_drawings():
    assert "12645-DRS EXTERNAL SHELTER V2" in rc.job_drawing_numbers(FILES)


def test_12645_heads_the_shelter_with_everything_under_it():
    g = _graph()
    root = g.get("product_root")
    assert root == "12645-DRS EXTERNAL SHELTER V2"
    assert set(g["children"].get(root) or []) == {"12645-01GA", "12645-02GA", "12645-03GA",
                                                  "ROLLER SHUTTER"}
    assert not (g.get("outside_product") or {})


def test_a_differently_worded_title_block_still_finds_the_one_top_sheet():
    edges = rc._bom_stated_edges([{"part_number": "12645-02GA",
                                   "parent": "12645 - DRS SHELTER", "qty": 1}],
                                 {}, {"12645-DRS EXTERNAL SHELTER V2", "12645-02GA"})
    assert edges == [("12645-02GA", "12645-DRS EXTERNAL SHELTER V2", 1.0)]


def test_a_descriptive_file_name_is_still_not_a_drawing():
    assert rc.job_drawing_numbers({"job_source_pdfs": ["Mod mount bracket set.pdf"]}) == []
