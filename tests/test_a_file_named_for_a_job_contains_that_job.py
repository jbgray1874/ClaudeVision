"""Two deliverables titled 10975-02, and every row in them was 10575.

    BOMs and routes — 10975-02
      10575-01-101  VERSION 1 - BACK WELDED ASSEMBLY
      10575-01-008  V1 - BACK FIXING PANEL
      ...  read from  10575-01-GA - V1 Cordless Vacuum Display [Rev D].PDF

Thirty BOM rows, fifty-eight route decisions, a Dyson cordless vacuum display — under the name
of the M&S table-top graphic holder, one digit away. 314 mentions of 10575 in the pair against
two of 10975, and both of those were the title we wrote ourselves.

NOTHING WAS FUZZY-MATCHING. The endpoint reads json/<label>.json exactly: no glob, no nearest
match. The RECORD at that path was another job's. So every row was internally consistent, every
column cited its source, the derivation sheet explained the method — and the file was wrong
about the only thing that cannot be checked by reading it.

That is the worst shape a deliverable can take. A wrong number gets argued with. A right
document about the wrong job gets quoted.

THE TEST IS THE WEAKEST ONE THAT STILL CATCHES IT, deliberately. The label is usually the
FOLDER, and the folder is often not the drawing number: 0355255 is the folder for a job whose
parts are all 10975-02-*, and refusing that would be a false alarm on a legitimate pack —
which is how a guard becomes something people switch off. But 0355255 appears in the drawing
filenames, so a mention test passes it. A record that never says the word AT ALL is the case
worth stopping, and it is exactly the case that happened.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bom_and_route_extract import (WrongJobRecord, record_mentions_job,   # noqa: E402
                                   write_both)

# The two records, as they actually were.
DYSON = {
    "job_number": "10575-01-GA",
    "parts": [{"part_number": "10575-01-101", "description": "BACK WELDED ASSEMBLY"},
              {"part_number": "10575-01-008", "description": "V1 - BACK FIXING PANEL"}],
    "files": ["10575-01-GA - V1 Cordless Vacuum Display [Rev D].PDF",
              "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"],
}
HOLDER = {
    "job_number": "10975-02",
    "parts": [{"part_number": "10975-02-A01", "description": "L-STAND"},
              {"part_number": "10975-02-G01", "description": "GRAPHIC"}],
    "files": ["0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"],
}


# ── the failure ──────────────────────────────────────────────────────────────────────────

def test_the_dyson_record_is_not_the_graphic_holder():
    assert record_mentions_job(DYSON, "10975-02") is False


def test_writing_it_under_that_name_is_refused():
    """A file that is wrong about its own subject is worse than no file, because it is
    quoted rather than argued with."""
    with pytest.raises(WrongJobRecord) as err:
        write_both(DYSON, ROOT / "does-not-matter", job="10975-02")
    assert "never mentions 10975-02" in str(err.value)


def test_nothing_is_written_when_it_refuses(tmp_path):
    with pytest.raises(WrongJobRecord):
        write_both(DYSON, tmp_path, job="10975-02")
    assert list(tmp_path.glob("*")) == []


# ── and the legitimate cases still pass ──────────────────────────────────────────────────

def test_the_folder_name_is_not_the_drawing_number_and_that_is_fine():
    """0355255 is the folder; every part is 10975-02-*. A guard that refused this would be
    a false alarm on a real pack, and a guard people switch off is not a guard."""
    assert record_mentions_job(HOLDER, "0355255") is True


def test_the_job_matching_its_own_record_passes():
    assert record_mentions_job(HOLDER, "10975-02") is True
    assert record_mentions_job(DYSON, "10575-01") is True


def test_punctuation_is_not_identity():
    """10975-02, 10975_02 and 1097502 are one job written three ways."""
    for spelling in ("10975-02", "10975_02", "1097502", "10975 02"):
        assert record_mentions_job(HOLDER, spelling) is True, spelling


def test_no_job_asked_for_is_not_a_contradiction():
    """Nothing to be wrong about. The extract is still allowed to run unnamed."""
    assert record_mentions_job(HOLDER, "") is True
    assert record_mentions_job(HOLDER, None) is True


def test_a_record_it_cannot_serialise_is_not_condemned():
    """An unserialisable record is a reason to say nothing, not to refuse the job — the
    guard exists to catch a wrong subject, not to become a new way for runs to fail."""
    class Awkward:
        def __repr__(self):
            return "10975-02"
    assert record_mentions_job({"thing": Awkward()}, "10975-02") is True


def test_the_reason_is_recorded_where_the_refusal_is():
    src = (ROOT / "src" / "bom_and_route_extract.py").read_text(encoding="utf-8")
    assert "314 mentions of 10575 against two of 10975" in src
    assert "cannot be seen by reading it" in src


def test_a_record_that_names_no_job_is_allowed_through():
    """NOTHING TO CONTRADICT IS NOT A CONTRADICTION, and the first cut of this got it wrong.

    It refused an empty record, a malformed one and a pack that yielded nothing — breaking
    test_a_malformed_record_never_raises_into_the_page, which exists because this is launched
    from the estimating page and must never be the reason that page errors.

    Only a record naming SOME OTHER job is the case worth stopping. That is what 10975-02's
    was: thirty rows of 10575 and not one mention of the job on the cover."""
    for harmless in ({}, {"job_number": "empty"}, {"pages": "wrong type"},
                     {"parts": []}, {"note": "no drawings were supplied"}):
        assert record_mentions_job(harmless, "10975-02") is True, harmless


def test_it_still_refuses_the_record_that_names_another_job():
    """The line between the two: a job-shaped number that is not the one asked for."""
    assert record_mentions_job({"parts": [{"part_number": "10575-01"}]}, "10975-02") is False


def test_an_empty_record_still_writes_its_two_files(tmp_path):
    """The contract the guard must not break — an extract that writes nothing when a pack
    yielded nothing is indistinguishable from one that failed."""
    out = write_both({"job_number": "empty"}, tmp_path, job="empty", want="both")
    assert out["xlsx"] and out["html"]
