r"""A decision arrives with a pull. It is not copied to a share by hand.

James Gray, 17 September 2026:

    "config needs to be in config files. not json files lying around and being copied
     manually around."

THE MECHANISM THAT WAS REPLACED, AND THE THREE WAYS IT FAILED.

A job's rulings lived in `<drawing>_confirmed.json`, written into the repository and then
COPIED BY HAND to the job folder on the share before a run.

  1  It was invisible to git. The blanket `*.json` rule kept every one of them out, so
     7332-01's rulings are recorded in the change register as delivered and were never in a
     commit. Nobody outside the container that wrote them could have them.
  2  A run with no file applied no rulings and said nothing about it. An answered question
     and an unasked one looked identical.
  3  Two machines could hold different answers with nothing to compare. A decision nobody
     can diff is not a record of anything.

And a fourth, found while moving it: `load_corrections` REQUIRED a `parts` block and threw
away any file without one — whole, silently, reporting "nothing to apply" about a file that
had plenty. 11908-21's own answers file is exactly that shape, because Tony had no
dimension to correct: a delivery exclusion and a banded length, and no readings at all.

WHAT IS AND IS NOT IN THE CONFIG. `SHOP_STATED` is how SDI WORKS — the weld allowance, the
joinery rates. `JOB_DECISIONS` is what a person DECIDED about one job. Both outrank anything
the engine derives; both belong in a versioned file. Neither may hold a price: a figure
typed into either would read on a sheet exactly like one the engine sourced.

A file beside the drawings is still read, because an estimator at the share may write one,
and it wins where both answer the same question — with the overlap REPORTED, because two
answers to one question is not a record either.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import estimator_confirmed as ec  # noqa: E402


# ── the rulings are in the repository, and they parse ────────────────────────────────

def test_tonys_rulings_are_config_and_need_no_copying():
    got, problems = ec.decisions_from_config("11908-21")
    assert got["estimator_decisions"]["commercial_excluded"] == ["DELIVERY"]
    assert got["estimator_decisions"]["banded_metres"] == {"per_unit": 5.0}
    assert got["confirmed_by"] == "Tony Ford"
    assert problems == []


def test_howards_rulings_came_with_them():
    """D-102 records these as delivered and they were never in a commit."""
    got, problems = ec.decisions_from_config("7332-01")
    dec = got["estimator_decisions"]
    assert dec["operations_off"] == {"7332-01-002": ["tube_bending"]}
    assert dec["throughput_per_hour"]["Laser (Acrylic)"] == 95
    assert len(dec["nesting_groups"]["003 and 004 on one laser program"]) == 2
    assert problems == []


def test_a_pack_filename_finds_its_own_job():
    """The run has a PDF name, not a tidy drawing number. `0359967_SUNGLASSES
    TRAY_11908-21 GA_REV A.PDF` is 11908-21's pack."""
    got, _ = ec.decisions_from_config("0359967_SUNGLASSES TRAY_11908-21 GA_REV A.PDF")
    assert got["confirmed_by"] == "Tony Ford"


def test_another_job_gets_nothing():
    """A ruling governs the job it was made about. Four shared digits is a collision, not
    a match."""
    assert ec.decisions_from_config("12345-99") == ({}, [])
    assert ec.decisions_from_config("1190") == ({}, [])


def test_every_entry_is_valid_and_carries_its_owner():
    """A malformed ruling that silently does nothing is the failure the file had every
    time. Each entry is validated through the same reader an answers file goes through."""
    for key in config.JOB_DECISIONS:
        got, problems = ec.decisions_from_config(key)
        assert problems == [], (key, problems)
        assert got.get("estimator_decisions"), key
        assert got.get("confirmed_by"), f"{key}: nobody's name on the ruling"
        assert got.get("confirmed_on"), f"{key}: no date on the ruling"


def test_no_price_is_typed_into_a_ruling():
    """D-078. A figure here would read on the sheet exactly like one the engine sourced,
    and the pricing keys are the ones that could carry one."""
    for key, block in config.JOB_DECISIONS.items():
        dec = block.get("estimator_decisions") or {}
        for banned in ("plating_gbp_per_unit", "freight_gbp", "gbp_per_metre",
                       "price_gbp", "rate_gbp"):
            assert banned not in dec, f"{key} carries {banned}"


# ── and the loose files are gone ─────────────────────────────────────────────────────

def test_no_answers_json_is_left_lying_in_the_repository():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    strays = sorted((root / "docs" / "answers").glob("*_confirmed.json")) \
        if (root / "docs" / "answers").is_dir() else []
    assert not strays, (
        f"{[p.name for p in strays]} — a ruling belongs in config.JOB_DECISIONS, not in a "
        f"file to be copied to the share by hand")


# ── a decisions-only file is not an empty file ───────────────────────────────────────

def _write(tmp_path, payload):
    p = tmp_path / "11908-21_confirmed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_a_file_with_no_readings_still_carries_its_rulings(tmp_path):
    """The shape Tony's file had: a decision and no dimension to correct. It was thrown
    away whole, with one line saying "nothing to apply"."""
    path = _write(tmp_path, {"confirmed_by": "Tony Ford", "confirmed_on": "2026-09-17",
                             "estimator_decisions": {"commercial_excluded": ["DELIVERY"]}})
    data, problems = ec.load_corrections(path)
    assert data.get("estimator_decisions") == {"commercial_excluded": ["DELIVERY"]}
    assert not any("nothing to apply" in p for p in problems)


def test_a_file_with_neither_is_still_reported(tmp_path):
    path = _write(tmp_path, {"confirmed_by": "Tony Ford"})
    data, problems = ec.load_corrections(path)
    assert data == {}
    assert any("nothing to apply" in p for p in problems)


def test_a_readings_only_file_behaves_exactly_as_it_always_did(tmp_path):
    """The control. Every existing answers file is this shape."""
    path = _write(tmp_path, {"confirmed_by": "Howard Thurley",
                             "parts": {"7332-01-008": {"thickness_mm": 1.0,
                                                       "basis": "read",
                                                       "read_from": "his 15 Sep reply"}}})
    data, problems = ec.load_corrections(path)
    assert data["parts"]["7332-01-008"]["thickness_mm"] == 1.0
    assert problems == []


# ── merged, with the file on top, and the overlap said out loud ──────────────────────

def test_config_applies_when_there_is_no_file_at_all():
    data, problems = ec.merge_config_decisions({}, "11908-21")
    assert data["estimator_decisions"]["banded_metres"] == {"per_unit": 5.0}
    assert problems == []


def test_a_file_beside_the_drawings_wins_and_says_so():
    """An estimator who has just written one is answering later than the repository."""
    file_data = {"confirmed_by": "Tony Ford", "parts": {},
                 "estimator_decisions": {"banded_metres": {"per_unit": 7.5}}}
    data, problems = ec.merge_config_decisions(file_data, "11908-21")
    assert data["estimator_decisions"]["banded_metres"] == {"per_unit": 7.5}
    # and config's other ruling is not lost by the file existing
    assert data["estimator_decisions"]["commercial_excluded"] == ["DELIVERY"]
    assert any("ruled in BOTH" in p for p in problems)


def test_a_job_with_no_config_entry_is_the_file_alone():
    file_data = {"confirmed_by": "X", "parts": {},
                 "estimator_decisions": {"commercial_excluded": ["PACKAGING"]}}
    data, problems = ec.merge_config_decisions(file_data, "12345-99")
    assert data == file_data
    assert problems == []


# ── and the run reads it without anything being copied ───────────────────────────────

def test_the_scan_asks_config_and_not_only_the_folder():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "file_scan.py"
           ).read_text(encoding="utf-8")
    assert "_ec.merge_config_decisions(" in src
    assert "if _ec_path or _ec_data.get(\"estimator_decisions\"):" in src, (
        "the decisions block still runs only when a file was found on the share")
