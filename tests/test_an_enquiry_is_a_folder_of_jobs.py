"""An enquiry is a folder; each sub-folder is one job. The engine reads the tree, not a command.

The gate this proves: a folder drop is turned into a manifest of jobs BEFORE anything is priced,
and a malformed drop is refused with a reason rather than silently costing three of four jobs or
pricing an empty pack at zero. Everything keys on the folder tree and the reader's own file
extensions — no customer, no job-number pattern, no filename — so a new enquiry needs no code.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import enquiry  # noqa: E402


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x")


def _job(root, name, *drawings):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    for f in drawings:
        _touch(os.path.join(d, f))
    return d


# ── the happy shape ──────────────────────────────────────────────────────────────────

def test_each_sub_folder_is_one_job_named_by_the_folder(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _job(root, "11650-04-SA01", "sa.pdf", "flats/panel.dxf")
    m = enquiry.read_enquiry(root)
    assert m["ok"] is True
    ids = {j["identity"] for j in m["jobs"]}
    assert ids == {"11650-00-GA", "11650-04-SA01"}


def test_drawings_are_found_at_any_depth_within_a_job(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-04", "ga.pdf", "flats/dxf/left.dxf", "flats/dxf/right.dxf")
    m = enquiry.read_enquiry(root)
    card = m["jobs"][0]
    assert card["drawing_count"] == 3, "a flat in a nested sub-folder was not counted"


def test_dwg_only_job_is_not_empty(tmp_path):
    """DWG is converted to DXF before reading, so a DWG-flats pack is a real job, not an empty
    one. Keyed on the reader's capability (config), not on a hand-listed extension."""
    root = str(tmp_path / "8352")
    _job(root, "8352-010", "part.dwg")
    m = enquiry.read_enquiry(root)
    assert m["ok"] is True
    assert m["jobs"][0]["drawing_count"] == 1


# ── the refusals: the whole reason this stage exists ─────────────────────────────────

def test_a_loose_drawing_at_the_top_refuses_the_enquiry(tmp_path):
    """A flat with no job folder could belong to either neighbour. The enquiry is refused, not
    guessed, and the loose file is named."""
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _touch(os.path.join(root, "orphan.dxf"))
    m = enquiry.read_enquiry(root)
    assert m["ok"] is False
    assert "orphan.dxf" in m["loose_drawings"]
    assert any("loose at the enquiry top" in r for r in m["refusals"])


def test_a_covering_file_at_the_top_is_surfaced_not_refused(tmp_path):
    """An enquiry spreadsheet or a covering email legitimately lives at enquiry level. It is
    listed so it is not mistaken for a job, but it does not block a clean enquiry."""
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _touch(os.path.join(root, "enquiry.xlsx"))
    m = enquiry.read_enquiry(root)
    assert m["ok"] is True, "a non-drawing top-level file wrongly blocked the enquiry"
    assert "enquiry.xlsx" in m["loose_other_files"]


def test_an_empty_job_folder_is_refused_not_priced_at_zero(tmp_path):
    """An empty pack costed at nothing reads as a free job. It is held out with its reason on
    the record; the enquiry with one good job and one empty folder does not go through."""
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _job(root, "11650-09-EMPTY")            # no drawings
    m = enquiry.read_enquiry(root)
    assert "11650-09-EMPTY" in m["empty_job_folders"]
    assert m["ok"] is False
    assert any("holds no readable drawing" in r for r in m["refusals"])


def test_a_non_drawing_only_folder_is_empty(tmp_path):
    """A folder of notes and photographs is not a pack the engine can price."""
    root = str(tmp_path / "11650")
    j = _job(root, "11650-01")
    _touch(os.path.join(j, "notes.txt"))
    _touch(os.path.join(j, "photo.jpg"))
    m = enquiry.read_enquiry(root)
    assert "11650-01" in m["empty_job_folders"]


def test_an_enquiry_with_no_job_folders_is_refused(tmp_path):
    root = str(tmp_path / "empty-enquiry")
    os.makedirs(root)
    m = enquiry.read_enquiry(root)
    assert m["ok"] is False
    assert any("no job sub-folders" in r for r in m["refusals"])


def test_a_missing_enquiry_folder_is_refused_cleanly(tmp_path):
    m = enquiry.read_enquiry(str(tmp_path / "does-not-exist"))
    assert m["ok"] is False
    assert any("is not a folder" in r for r in m["refusals"])


# ── order quantity: the divisor is on the record ─────────────────────────────────────

def test_order_quantity_is_stamped_per_job(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _job(root, "11650-04-SA01", "sa.pdf")
    m = enquiry.read_enquiry(root, order_qty_by_job={"11650-00-GA": 45, "11650-04-SA01": 5})
    by_id = {j["identity"]: j for j in m["jobs"]}
    assert by_id["11650-00-GA"]["order_quantity"] == 45
    assert by_id["11650-00-GA"]["priced_at"] == "priced at 45 off"
    assert by_id["11650-04-SA01"]["order_quantity"] == 5


def test_a_job_with_no_quantity_says_it_is_inferred(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    m = enquiry.read_enquiry(root)
    assert m["jobs"][0]["order_quantity"] is None
    assert "infers" in m["jobs"][0]["priced_at"]


def test_default_order_quantity_fills_unlisted_jobs(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "A", "a.pdf")
    _job(root, "B", "b.pdf")
    m = enquiry.read_enquiry(root, order_qty_by_job={"A": 45}, default_order_qty=10)
    by_id = {j["identity"]: j for j in m["jobs"]}
    assert by_id["A"]["order_quantity"] == 45
    assert by_id["B"]["order_quantity"] == 10, "the default did not fill the unlisted job"


# ── setup-heavy: flagged, never altered ──────────────────────────────────────────────

def test_a_short_run_is_flagged_setup_heavy(tmp_path):
    root = str(tmp_path / "10575")
    _job(root, "10575-02", "ga.pdf")
    m = enquiry.read_enquiry(root, order_qty_by_job={"10575-02": 1})
    card = m["jobs"][0]
    assert card["setup_heavy"] is True
    assert any("short run" in w for w in card["warnings"])


def test_a_normal_run_is_not_flagged_setup_heavy(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    m = enquiry.read_enquiry(root, order_qty_by_job={"11650-00-GA": 45})
    assert m["jobs"][0]["setup_heavy"] is False
    assert not any("short run" in w for w in m["jobs"][0]["warnings"])


def test_the_boundary_qty_itself_is_not_setup_heavy(tmp_path):
    """The threshold is 'below N', so N off is a normal run. Pins BOTH the boolean AND the
    warning text at the boundary — they carry the same threshold in two expressions, and an
    off-by-one in either would flag every job at exactly the threshold or none just under it."""
    root = str(tmp_path / "j")
    _job(root, "J", "ga.pdf")
    at = enquiry.read_enquiry(root, order_qty_by_job={"J": enquiry.SETUP_HEAVY_BELOW_QTY})["jobs"][0]
    assert at["setup_heavy"] is False
    assert not any("short run" in w for w in at["warnings"])
    below = enquiry.read_enquiry(
        root, order_qty_by_job={"J": enquiry.SETUP_HEAVY_BELOW_QTY - 1})["jobs"][0]
    assert below["setup_heavy"] is True
    assert any("short run" in w for w in below["warnings"])


# ── identity naming: a note, never a refusal ─────────────────────────────────────────

def test_an_oddly_named_folder_is_noted_but_still_a_job(tmp_path):
    root = str(tmp_path / "enq")
    _job(root, "New folder", "ga.pdf")
    m = enquiry.read_enquiry(root)
    assert m["ok"] is True, "an unusual folder name wrongly refused a real job"
    assert any("not shaped like a job number" in w for w in m["jobs"][0]["warnings"])


def test_a_job_number_name_raises_no_naming_note(tmp_path):
    root = str(tmp_path / "enq")
    _job(root, "8352_010-GA", "ga.pdf")
    m = enquiry.read_enquiry(root)
    assert not any("not shaped like a job number" in w for w in m["jobs"][0]["warnings"])


# ── the one line an operator reads ───────────────────────────────────────────────────

def test_one_line_ready(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _job(root, "11650-04", "sa.pdf")
    line = enquiry.one_line(enquiry.read_enquiry(root))
    assert "2 job(s) ready" in line


def test_one_line_flags_short_runs(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-04", "sa.pdf")
    line = enquiry.one_line(enquiry.read_enquiry(root, order_qty_by_job={"11650-04": 2}))
    assert "short runs to confirm" in line and "11650-04" in line


def test_one_line_not_ready_leads_with_the_fix(tmp_path):
    root = str(tmp_path / "11650")
    _job(root, "11650-00-GA", "ga.pdf")
    _touch(os.path.join(root, "orphan.dxf"))
    line = enquiry.one_line(enquiry.read_enquiry(root))
    assert "not ready" in line
