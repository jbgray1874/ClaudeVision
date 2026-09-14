"""The customer quotation went out headed:

    Quotation 12349-02-69-GA — assembly (from the SolidWorks model's own tree)

An assembly parent minted from the SolidWorks component tree has no drawing sheet, so it has
no description — it carries the sentence saying where it came from instead. On 12349-02 that
minted parent is also the OUTERMOST root of the graph, so it became the unit's identity: the
quotation headline, the Description box on the estimate, and the alt text of the general
arrangement all read as a note the engine had written to itself.

READING THE MODELS MADE THE HEADER WORSE THAN LEAVING IT BLANK, which is the thing to notice.
The empty Description box was a fault worth fixing and was fixed; this replaced it with a
sentence that looks like an answer, in front of a customer, on a page nobody would think to
check twice.

So a note is refused and the search carries on into the roots that do have a description —
12349-02-69, "GRAVITY FEEDER MODULES", which the job's own provenance tab has printed all
along. Nothing is invented: where no root can say what the unit is, nothing is written, which
is what this did before the models were ever read.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from client_quote_html import _drawing_identity, _is_an_engine_note      # noqa: E402


# ── what counts as the engine talking about itself ───────────────────────────────────────

def test_the_minted_parent_sentence_is_a_note():
    assert _is_an_engine_note("assembly (from the SolidWorks model's own tree)")
    assert _is_an_engine_note("assembly parent minted from the SolidWorks component tree — "
                              "no drawing sheet of its own")


def test_a_bare_kind_word_is_a_note():
    """"assembly" is what a thing IS. A quotation headed "assembly" tells a customer nothing
    the drawing number above it did not."""
    for word in ("assembly", "Assembly", "sub-assembly", "WELDMENT", " part ", "component"):
        assert _is_an_engine_note(word), word


def test_a_real_description_is_not_a_note():
    for good in ("GRAVITY FEEDER MODULES", "LID", "FRONT COVER", "PACKER",
                 "GRAVITY FEEDER FABRICATION", "ASSEMBLY JIG BRACKET",
                 "SUB-ASSEMBLY, LOWER SHELF"):
        assert not _is_an_engine_note(good), good


def test_nothing_at_all_is_not_a_note():
    """Absent and wrong are different, and only one of them has something to refuse."""
    for empty in ("", "   ", None):
        assert not _is_an_engine_note(empty)


# ── the header falls through to a root that can say what the unit is ─────────────────────

def _summary(top, roots, records):
    return {"canonical_route_shadow": {"top_assembly": top, "top_assemblies": list(roots),
                                       "nodes": []},
            "parts": records}


def _rec(pn, desc):
    return {"part_number": pn, "description": desc}


def test_the_gravity_feeder_quote_is_headed_by_the_product():
    s = _summary("12349-02-69-GA", ["12349-02-69-GA", "12349-02-69"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)"),
                  _rec("12349-02-69", "GRAVITY FEEDER MODULES")])
    _num, _rev, desc = _drawing_identity(s, "12349-02")
    assert desc == "GRAVITY FEEDER MODULES"


def test_the_minted_parent_is_usually_the_ONLY_root():
    """AND THIS IS THE CASE, NOT AN EDGE OF IT. The SolidWorks tree mints one node above
    everything on the job, so it becomes the only root — and a search confined to the roots
    then has nowhere to go. The Description box came out EMPTY on the 14:42 run of 12349-02:
    the note was correctly refused and nothing replaced it, which is the fault that was fixed
    before the models were ever read, arriving back by another door."""
    s = _summary("12349-02-69-GA", ["12349-02-69-GA"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)"),
                  _rec("12349-02-69", "GRAVITY FEEDER MODULES"),
                  _rec("12349-02-69-100", "GRAVITY FEEDER MODULES, 3 WIDE"),
                  _rec("12349-02-69-04M", "LID")])
    assert _drawing_identity(s, "12349-02")[2] == "GRAVITY FEEDER MODULES"


def test_the_records_search_still_respects_the_owning_number():
    s = _summary("12349-02-69-GA", ["12349-02-69-GA"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)"),
                  _rec("7332-01-101", "HARRODS STAND FRAME"),
                  _rec("12349-02-69", "GRAVITY FEEDER MODULES")])
    assert _drawing_identity(s, "12349-02")[2] == "GRAVITY FEEDER MODULES"


def test_the_note_never_survives_even_where_no_other_root_has_one():
    """Refusing it is not conditional on having something better. A blank Description is a
    gap; a sentence about the engine's internals is a wrong answer."""
    s = _summary("12349-02-69-GA", ["12349-02-69-GA"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)")])
    _num, _rev, desc = _drawing_identity(s, "12349-02")
    assert "SolidWorks model" not in desc
    assert desc in ("", "12349-02", "12349-02-69-GA"), desc


def test_a_root_this_drawing_does_not_own_is_not_preferred():
    """Another job's assembly staged in the same pack must not name this one's unit."""
    s = _summary("12349-02-69-GA", ["12349-02-69-GA", "7332-01-101", "12349-02-69"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)"),
                  _rec("7332-01-101", "HARRODS STAND FRAME"),
                  _rec("12349-02-69", "GRAVITY FEEDER MODULES")])
    assert _drawing_identity(s, "12349-02")[2] == "GRAVITY FEEDER MODULES"


def test_the_innermost_owned_root_wins():
    """Sorted by length, so the shortest owned code answers — the one nearest the drawing
    number, not a module three levels down."""
    s = _summary("12349-02-69-GA",
                 ["12349-02-69-GA", "12349-02-69-100", "12349-02-69"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)"),
                  _rec("12349-02-69-100", "GRAVITY FEEDER MODULES, 3 WIDE"),
                  _rec("12349-02-69", "GRAVITY FEEDER MODULES")])
    assert _drawing_identity(s, "12349-02")[2] == "GRAVITY FEEDER MODULES"


def test_a_title_block_description_is_still_what_it_always_was():
    """The drawing's own title block outranks every one of these and is untouched."""
    s = _summary("12349-02-69-GA", ["12349-02-69-GA"],
                 [_rec("12349-02-69-GA", "assembly (from the SolidWorks model's own tree)")])
    s["llm_full_extract"] = {"drawing_info": {"drawing_number": "12349-02-69-GA",
                                              "title": "GRAVITY FEEDERS", "revision": "A"}}
    num, rev, desc = _drawing_identity(s, "12349-02")
    assert (num, rev, desc) == ("12349-02-69-GA", "Rev A", "GRAVITY FEEDERS")


def test_a_job_whose_root_has_a_description_is_unchanged():
    """The ordinary path: one root, a real description, nothing to refuse."""
    s = _summary("7332-01-101", ["7332-01-101"], [_rec("7332-01-101", "HARRODS STAND")])
    assert _drawing_identity(s, "7332-01")[2] == "HARRODS STAND"
