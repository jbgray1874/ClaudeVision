"""A BOM line naming a drawing the pack does not contain is UNREAD, not free.

Job 11650's cabinet costed at GBP 7.37 a unit with GBP 1.81 of material -- a fragrance
coffret cabinet, at 45 off. Nothing was broken. The GA's bill of materials is
11650-01-GA, 11650-02-GA and 11650-03-GA, three sub-assemblies whose detail drawings are
not in the folder. The engine correctly declined to charge material on an assembly parent,
correctly found no leaves to charge it on, and produced a number that looks exactly like a
finished estimate for a nearly empty one.

That is the worst shape a wrong answer can take here, and it is not a pricing failure --
every individual decision was right. Only a check that compares what the BOM NAMES against
what the pack CONTAINS can say so.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invariants import (BLOCKING,                                   # noqa: E402
                        check_the_pack_contains_the_drawings_its_bom_names as check)


def _job(bom_rows, pages=(), parts=()):
    return {"document_analysis": {"bom_rows": list(bom_rows)},
            "pages": list(pages), "parts": list(parts)}


def _page(*drawing_numbers):
    return {"page_number": 1,
            "page_analysis": {"title_block": {"drawing_numbers": list(drawing_numbers)}}}


# ---------------------------------------------------------------------------
# the live failure
# ---------------------------------------------------------------------------
def test_a_cabinet_whose_children_are_not_in_the_pack_blocks():
    job = _job(
        [{"part_number": "11650-01-GA", "description": "DOOR ASSEMBLY", "quantity": 1},
         {"part_number": "11650-02-GA", "description": "TOP ASSEMBLY", "quantity": 1},
         {"part_number": "11650-03-GA", "description": "LH ARM ASSEMBLY", "quantity": 1}],
        pages=[_page("11650-00-GA")])

    out = check(job)

    assert len(out) == 1
    assert out[0]["severity"] == BLOCKING
    assert out[0]["detail"]["count"] == 3
    assert "11650-01-GA" in out[0]["message"]
    assert "incomplete pack, not a cheap job" in out[0]["message"], \
        "the message must say what the number means, not merely that a file is absent"


def test_a_child_whose_detail_sheet_is_in_the_pack_is_not_flagged():
    job = _job(
        [{"part_number": "11650-01-GA", "description": "DOOR ASSEMBLY", "quantity": 1}],
        pages=[_page("11650-00-GA"), _page("11650-01-GA")])
    assert check(job) == []


def test_a_child_that_was_measured_counts_as_read():
    """A part with geometry was read by something, whatever the pages say -- a DXF or a
    model reaches parts that no PDF page names."""
    job = _job(
        [{"part_number": "11650-01-GA", "description": "DOOR", "quantity": 1}],
        pages=[_page("11650-00-GA")],
        parts=[{"part_number": "11650-01-GA", "blank_length_mm": 420.0}])
    assert check(job) == []


# ---------------------------------------------------------------------------
# what must NOT be asked
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code,desc", [
    ("FIXING", "M4x8mm BUTTON HEAD SCREW; BZP"),
    ("BI-BOLTBZP", "Bolt Bzp"),
    ("P/P TBM571", "LARGE LEAFLET POCKET"),
    ("PACKAGING", "Packaging"),
])
def test_a_bought_in_line_names_a_catalogue_item_not_a_drawing(code, desc):
    """A fastener, a lock, a leaflet pocket has no detail sheet in the pack and never
    will. Flagging those would put a blocker on every job in the system."""
    job = _job([{"part_number": code, "description": desc, "quantity": 4}],
               pages=[_page("11650-00-GA")])
    assert check(job) == []


def test_a_job_with_no_bom_says_nothing():
    """check_both_bom_readers_ran owns that failure. Reporting clean here would be a lie
    about a job with no BOM; reporting a blocker would be the wrong blocker."""
    assert check(_job([])) == []


def test_an_unreadable_summary_is_unevaluated_not_clean():
    out = check("not a job")
    assert len(out) == 1
    assert out[0]["severity"] == "unverified"
    assert "verified nothing" in out[0]["message"]


# ---------------------------------------------------------------------------
# the wiring
# ---------------------------------------------------------------------------
def test_the_check_is_registered():
    """Built is not wired. A check absent from the registry runs on no job at all."""
    import invariants
    assert check in invariants.CHECKS, "the check exists and nothing calls it"


def test_it_fires_through_check_job():
    """End to end, because a check can be registered and still be skipped by a guard
    earlier in the run."""
    import invariants
    job = _job(
        [{"part_number": "11650-01-GA", "description": "DOOR ASSEMBLY", "quantity": 1}],
        pages=[_page("11650-00-GA")])

    result = invariants.check_job(job, write_back=False)
    # "violations", not "findings". The first version of this asked for a key check_job
    # does not return, got [] and failed -- which was luck: a test that reads the wrong key
    # reports absence for every check ever written, so it would have passed the moment
    # somebody asserted the opposite.
    codes = [f.get("code") for f in (result.get("violations") or [])]
    assert "bom_names_a_drawing_the_pack_does_not_contain" in codes, \
        f"registered but never reached check_job. Codes seen: {sorted(set(codes))}"
    assert result["blocking"] >= 1


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
