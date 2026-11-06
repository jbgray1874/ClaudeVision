"""A flat is bound to a part only where ALL its segments are the part's (D-434).

8188-08's 17:37 book: the folder holds "8188-29-002 3mm MS.DXF" (the frame base) and
"8188-12-002 MS 2MM.DXF" (a swing-stopper part). The segment rung bound the stopper's file to
the base on the shared "002"; two flats at two gauges made the base an assembly of two minted
pieces; the product scope set both aside, and the 1,292 x 200 x 3 base left the book.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_job_merge as djm                                       # noqa: E402

_JOB = {"8188-29-002": {"part_number": "8188-29-002"},
        "8188-29-001": {"part_number": "8188-29-001"},
        "8188-12-001": {"part_number": "8188-12-001"},
        "8188-12-GA": {"part_number": "8188-12-GA"}}


def _bind(name, parts=None):
    pn = djm.part_number_from_dxf_path(Path(name))
    part, basis = djm._lookup_part_with_basis(parts or _JOB, pn)
    return pn, (part or {}).get("part_number"), basis


def test_another_drawings_file_is_not_bound_on_a_shared_last_segment():
    pn, bound, _ = _bind("8188-12-002 MS 2MM.DXF")
    assert pn == "8188-12-002" and bound is None


def test_the_parts_own_file_still_binds_exactly():
    assert _bind("8188-29-002 3mm MS.DXF")[1:] == ("8188-29-002", "exact")


def test_a_shorter_code_still_finds_the_part_it_ends():
    """The rung itself, given a code whose segments are all the part's last ones."""
    part, basis = djm._lookup_part_with_basis({"8188-12-002": {"part_number": "8188-12-002"}},
                                              "12-002")
    assert (part or {}).get("part_number") == "8188-12-002" and basis == "segment"


def test_the_stoppers_file_stays_with_its_own_family():
    """Unbound, it is still this job's code, so it is not refused as a foreign drawing — it
    goes the orphan way, and the product scope sets it aside as not linked."""
    assert djm._dxf_code_is_in_this_job("8188-12-002", _JOB)
