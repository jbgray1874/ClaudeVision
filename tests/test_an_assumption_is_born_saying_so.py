"""Two small holes of the same shape: a fact with no source, and a failure with no reason.

(1) A QUANTITY OF ONE THAT NOBODY CLAIMED. _empty_part_record defaults quantity to 1. Every
    caller that KNOWS the quantity passes None and submits the real figure through the
    resolver immediately after — part_index from the BOM row, document_builder twice,
    drawing_job_merge for a synthesised part. One caller does not: part_index creates a record
    for a part it has only seen NAMED on a page, and takes the default. That record carried a
    quantity of 1 with no source at all, and 11650-04 came back with three parts in exactly
    that state.

    An unattributed datum is invisible to arbitration. The next pass has nothing to weigh
    itself against, so it either overwrites a real reading or leaves a guess standing, and
    nothing anywhere says which happened. `inference` is rank 20 — the bottom of the table —
    so any real observation beats it and the assumption survives only where nothing better was
    ever read.

(2) TWO REASONS, ONE SENTENCE. convert_dwgs already distinguishes "the ODA File Converter is
    not installed" (a five-minute free download) from "the converter ran and produced no DXF"
    (3D DWGs, which hold no flat pattern — nothing to do). The invariant reported neither, so
    the only sentence anybody read told them a tool would fix it without saying whether the
    tool was even present. Two different actions, one message, and the one that costs nothing
    to fix looked like the one that cannot be fixed at all.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import document_builder  # noqa: E402
import invariants  # noqa: E402
import source_precedence as sp  # noqa: E402


# ── (1) the assumed quantity ─────────────────────────────────────────────────────────

def test_the_default_quantity_says_it_is_an_assumption():
    record = document_builder._empty_part_record("11650-04-01A")
    assert record["quantity"] == 1
    assert record["quantity_source"] == "inference"


def test_the_assumption_ranks_below_everything_that_read_a_drawing():
    """The point of attributing it. At rank 20 a BOM row, a title block or a model all beat
    it; unattributed it ranked 0 and was equally invisible, which is not the same thing —
    arbitration could not record that it had been overruled."""
    record = document_builder._empty_part_record("11650-04-01A")
    assert sp.rank(record["quantity_source"]) == 20
    for stronger in ("bom_tree", "drawing_deterministic", "solidworks_api", "dxf"):
        assert sp.rank(stronger) > sp.rank(record["quantity_source"]), stronger


def test_a_real_quantity_beats_the_assumption_and_is_recorded_as_doing_so():
    record = document_builder._empty_part_record("11650-04-01A")
    assert sp.apply_field(record, "quantity", 4, "bom_tree") is True
    assert record["quantity"] == 4
    assert record["quantity_source"] == "bom_tree"


def test_a_caller_that_supplies_no_quantity_gets_no_source_either():
    """Every caller that passes None is about to submit the real figure through the resolver.
    Finding a source already sitting there would have apply_field arbitrating against a claim
    nobody made — and inference (20) losing to bom_tree (60) is the RIGHT outcome reached for
    the wrong reason, which is worse than a wrong one because it looks correct."""
    record = document_builder._empty_part_record("X", quantity=None)
    assert record["quantity"] is None
    assert "quantity_source" not in record


def test_the_record_a_named_part_is_born_with_is_attributed():
    """part_index:121 — a part seen only NAMED on a page, with no BOM row behind it. This is
    the caller that produced the unattributed quantities, and it goes through the same
    constructor, so it must come out attributed without part_index changing at all."""
    import inspect
    import part_index

    # part_index receives the constructor by INJECTION, so fixing the default only reaches it
    # if that is the function injected. Asserted on the wiring, because a fix in a constructor
    # nobody calls is "built is not wired" with the pieces swapped round.
    source = inspect.getsource(part_index.build_part_index)
    assert "empty_part_record(part_number=pn)" in source, (
        "part_index no longer constructs a named-only part this way; re-check where that "
        "record's quantity comes from now")
    injected = [ln for ln in inspect.getsource(document_builder).splitlines()
                if "empty_part_record=" in ln]
    assert injected and "_empty_part_record" in injected[0], (
        "part_index is handed a different constructor than the one attributing the default")
    assert document_builder._empty_part_record("11650-04-01A")["quantity_source"] == "inference"


def test_the_attribution_check_stops_reporting_it():
    """THE CALLER, NOT THE CONSTRUCTOR. The finding was raised by invariants reading a job, so
    that is where it has to stop being raised."""
    part = document_builder._empty_part_record("11650-04-01A")
    part["normalized_material"] = "ABS"
    part["material_source"] = "solidworks_api"
    found = invariants.check_evidence_is_attributed({"part_estimates": [part]})
    fields = found[0]["detail"]["fields"] if found else {}
    assert "quantity" not in fields, f"quantity still reported unattributed: {found}"


# ── (2) why the DWGs were not converted ──────────────────────────────────────────────

def _message(conversion=None, unread=("a.DWG", "b.DWG")):
    summary = {"cad_inputs": {"present": True, "unread": list(unread)}}
    if conversion is not None:
        summary["dwg_conversion"] = conversion
    found = invariants.check_every_cad_file_was_used(summary)
    return found[0]["message"] if found else ""


NOT_INSTALLED = {"found": ["a.DWG"], "reason":
                 "2 DWG file(s) found and not converted: the ODA File Converter was not "
                 "located. It is a free standalone download; set config.DWG_CONVERTER_PATH "
                 "to its executable, or put it on PATH."}
RAN_EMPTY = {"found": ["a.DWG"], "converted": [], "reason":
             "the DWG converter ran (exit 0) but produced no DXF. The files may be 3D DWGs, "
             "which hold no flat pattern, or a version the converter cannot read."}


def test_a_missing_converter_is_named_as_missing():
    message = _message(NOT_INSTALLED)
    assert "was not located" in message
    assert "free standalone download" in message


def test_a_converter_that_ran_and_found_nothing_reads_differently():
    """The whole point. These two need different people to do different things — one is a
    download, the other is 3D models with no flat pattern in them and nothing to do at all."""
    missing = _message(NOT_INSTALLED)
    ran = _message(RAN_EMPTY)
    assert missing != ran
    assert "3D DWG" in ran and "3D DWG" not in missing
    assert "not located" not in ran


def test_a_partly_successful_conversion_says_the_converter_is_present():
    """Otherwise the advice to install a tool that is already installed and working sends
    somebody to fix a problem they do not have."""
    message = _message({"found": ["a.DWG", "c.DWG"], "converted": ["c.dxf"]})
    assert "converter DID run" in message
    assert "not located" not in message


def test_the_sentence_does_not_end_in_two_full_stops():
    """The reason is a whole sentence and this message adds its own stop. Small, and the kind
    of thing that makes a report read as unproofed."""
    assert ".." not in _message(NOT_INSTALLED)
    assert _message(NOT_INSTALLED).endswith(".")


def test_nothing_is_claimed_about_a_job_that_never_ran_the_converter():
    """No dwg_conversion record means the question was not asked on this job — inventing an
    answer for it is the absence-reported-as-a-clean-answer failure, in the message meant to
    end guessing."""
    message = _message(None)
    assert "ODA File Converter turns" in message, "the general advice still stands"
    assert "not located" not in message and "converter DID run" not in message


def test_a_job_with_no_dwgs_says_nothing_about_converters():
    message = _message(NOT_INSTALLED, unread=("model.STEP",))
    assert "ODA" not in message
    assert "skipped by design" in message
