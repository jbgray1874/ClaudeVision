"""A diagnostic that cannot tell "not deployed" from "does not work" sends the next fix the
wrong way.

WHAT HAPPENED. 11650-04's handed side panels inherited material on one hand and not the other,
and inherited no thickness at all — from a loop that writes both, through one resolver, in one
pass. That is not a possible outcome of that loop, so the real question was whether the loop
ran on the build that produced the sheet. Nothing on the record, the console or the spreadsheet
answered it, and a whole round of diagnosis went into a question a printed commit hash settles.

The tool this file guards prints, per part: the value of each arbitrated datum, WHO said it,
that source's rank, what it displaced, whether anything independent disagreed with it, and any
mirror provenance anywhere on the record — under the commit the engine is on.

THE TRAPS IT MUST NOT FALL INTO, both of which have been paid for already:

  * THE SOURCE KEY IS NOT ALWAYS "<field>_source". material, quantity and thickness record
    theirs as material_source / quantity_source / thickness_source. A fixture that used the
    convention made every assertion in an earlier handed-pair test pass with precedence
    completely broken, because the resolver saw rank 0 everywhere. The tool asks
    source_precedence rather than assuming.

  * AN ABSENCE MUST BE REPORTED AS AN ABSENCE. "No mirror provenance found" is not "the mirror
    did not run" — both readings have to reach the person reading it, or the tool has quietly
    answered a question it cannot answer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "diagnose"))

import engine_build  # noqa: E402
import source_precedence as sp  # noqa: E402
import where_did_this_fact_come_from as tool  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def _job(tmp_path, parts):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"part_estimates": parts}), encoding="utf-8")
    return str(path)


def _run(tmp_path, parts, *argv, capsys=None):
    path = _job(tmp_path, parts)
    tool.main([*argv, "--json", path])
    return capsys.readouterr().out


BASE = {
    "part_number": "11650-04-01A",
    "page_roles": ["detail"],
    "normalized_material": "ABS",
    "material_source": "solidworks_api",
    "normalized_thickness_mm": 2.2,
    "thickness_source": "title_block",
    "quantity": 2,
    "quantity_source": "bom_tree",
    "_displaced": {"normalized_material": [
        {"value": "PETG", "source": "title_block"},
        {"value": "PETG", "source": "drawing_deterministic"},
    ]},
    "material_estimate": {},
}

TWIN = {
    "part_number": "11650-04-01A-HANDED",
    "page_roles": ["assembly"],
    "normalized_material": "ABS",
    "material_source": "mirror_of_measured",
    "normalized_thickness_mm": 2.0,
    "thickness_source": "llm_extract",
    "mirror_of": "11650-04-01A",
    "material_estimate": {},
}

ORPHAN = {
    "part_number": "11650-04-03A-HANDED",
    "page_roles": ["assembly"],
    "normalized_material": "PETG",
    "material_source": "llm_extract",
    "normalized_thickness_mm": 2.0,
    "material_estimate": {},
}


def test_it_says_which_build_is_reading_the_estimate(tmp_path, capsys):
    """The whole reason the tool exists. Without this, "the fix is not live" and "the fix does
    not work" are the same output."""
    out = _run(tmp_path, [BASE], "11650-04-01A", capsys=capsys)
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert "READING it now:" in out
    assert head and head in out


def test_the_build_that_wrote_the_estimate_is_not_the_one_reading_it(tmp_path, capsys):
    """THE CONFLATION THIS TOOL EXISTS TO PREVENT, once committed inside the tool itself. An
    estimate written before a pull and read after it would have been reported under a commit
    containing fixes it never had — which is precisely the wrong answer to the only question
    being asked."""
    path = tmp_path / "job.json"
    path.write_text(json.dumps({
        "engine_build": {"commit": "deadbee", "branch": "old-branch", "dirty": False,
                         "subject": "a build from last week", "known": True},
        "part_estimates": [BASE],
    }), encoding="utf-8")
    tool.main(["11650-04-01A", "--json", str(path)])
    out = capsys.readouterr().out
    assert "WROTE this estimate:" in out and "deadbee" in out
    assert "a build from last week" in out
    assert "DIFFERENT BUILDS" in out


def test_an_estimate_with_no_stamp_says_it_has_none(tmp_path, capsys):
    """An unstamped document is one written before stamping existed — which is itself an
    answer about which fixes were live. Reporting the reader's build as if it were the
    writer's would be the lie."""
    out = _run(tmp_path, [BASE], "11650-04-01A", capsys=capsys)
    assert "NOT RECORDED" in out
    assert "DIFFERENT BUILDS" not in out


def test_an_uncommitted_engine_says_so():
    """A dirty checkout is not the commit it names, and a run from one cannot be reproduced
    from the hash. Asserted on the OUTPUT of the shared describer, not by grepping the file for
    the words — a guard that greps prose passes on a comment explaining the rule."""
    dirty = engine_build.one_line({"commit": "abc1234", "branch": "b", "dirty": True,
                                   "known": True})
    clean = engine_build.one_line({"commit": "abc1234", "branch": "b", "dirty": False,
                                   "known": True})
    unsure = engine_build.one_line({"commit": "abc1234", "branch": "b", "dirty": None,
                                    "known": True})
    assert "UNCOMMITTED" in dirty and "not reproducible" in dirty
    assert "UNCOMMITTED" not in clean
    # NOT SILENTLY "CLEAN". Being unable to ask git whether the tree is dirty is not the same
    # observation as a clean tree, and only one of them supports reproducing the run.
    assert "could not tell" in unsure


def test_an_engine_that_cannot_identify_itself_says_that_and_not_a_hash():
    assert "UNKNOWN" in engine_build.one_line({"known": False})


def test_it_reads_the_source_key_the_engine_actually_writes(tmp_path, capsys):
    """THE TRAP. material / quantity / thickness do NOT use '<field>_source'. A tool that
    assumed the convention would report 'no source recorded' for exactly the three facts a
    price turns on — and would have shown a correctly-inherited handed part as an orphan."""
    out = _run(tmp_path, [BASE], "11650-04-01A", capsys=capsys)
    material_line = next(l for l in out.splitlines() if "normalized_material" in l)
    assert "no source" not in material_line
    assert "rank 90" in material_line, "the SolidWorks model ranks 90 and the tool must say so"
    thickness_line = next(l for l in out.splitlines() if "normalized_thickness_mm" in l)
    assert "rank 70" in thickness_line


def test_every_arbitrated_fact_reaches_the_printed_report(tmp_path, capsys):
    """A list typed into the tool goes stale the first time a fourth field is arbitrated, and
    the tool then prints a complete-looking report with one of them missing. Asserted on the
    OUTPUT, not on the constant: a constant that agrees with the resolver and never reaches the
    page is the same absence with a passing test over it."""
    out = _run(tmp_path, [BASE], "11650-04-01A", capsys=capsys)
    for field in sp._SOURCE_FIELDS:
        assert field in out, f"source_precedence arbitrates {field} and the report never says so"


def test_it_shows_what_the_winner_overwrote_and_who_agreed_against_it(tmp_path, capsys):
    """The prerequisite for any rule that would prefer two agreeing drawings over one lone
    model. If the tool cannot show the disagreement, nobody can argue about it."""
    out = _run(tmp_path, [BASE], "11650-04-01A", capsys=capsys)
    assert "displaced: PETG" in out
    assert "AGAINST IT: 2 independent source(s) said PETG" in out
    assert "drawing_deterministic" in out and "title_block" in out


def test_an_inherited_fact_is_visibly_inherited(tmp_path, capsys):
    out = _run(tmp_path, [TWIN], "11650-04-01A-HANDED", capsys=capsys)
    assert "MIRROR PROVENANCE:" in out
    assert "material_source = mirror_of_measured" in out
    assert "mirror_of = 11650-04-01A" in out


def test_a_fact_that_did_not_inherit_is_visibly_not_inherited(tmp_path, capsys):
    """The twin's thickness came from an LLM, not from its base. That is the finding, and the
    tool has to make it readable next to the material that DID inherit."""
    out = _run(tmp_path, [TWIN], "11650-04-01A-HANDED", capsys=capsys)
    thickness_line = next(l for l in out.splitlines() if "normalized_thickness_mm" in l)
    assert "mirror" not in thickness_line.lower()
    assert "rank 40" in thickness_line


def test_no_mirror_provenance_is_reported_as_an_absence_not_a_verdict(tmp_path, capsys):
    """AN ABSENCE REPORTED AS A CLEAN ANSWER is its own defect class. Both readings — never
    ran, or ran and recorded nothing — have to reach the reader."""
    out = _run(tmp_path, [ORPHAN], "11650-04-03A-HANDED", capsys=capsys)
    assert "NOTHING on this record says a mirror rule touched it" in out
    assert "never fired" in out and "recorded nothing" in out


def test_mirror_evidence_is_found_wherever_it_is_written(tmp_path, capsys):
    """Not at three named paths. The rule may record its provenance somewhere else tomorrow,
    and a tool that named the paths would report 'no mirror provenance' the day it did — which
    is the exact false negative it exists to rule out."""
    buried = dict(ORPHAN)
    buried["provenance"] = {"geometry": {"how": "mirrored from 11650-04-03A"}}
    out = _run(tmp_path, [buried], "11650-04-03A-HANDED", capsys=capsys)
    assert "mirrored from 11650-04-03A" in out
    assert "NOTHING on this record" not in out


def test_mirrors_finds_both_hands_using_the_engines_own_convention(tmp_path, capsys):
    out = _run(tmp_path, [BASE, TWIN, ORPHAN], "--mirrors", capsys=capsys)
    assert "11650-04-01A-HANDED" in out
    assert "11650-04-01A\n" in out, "the base must be reported beside its hand, or there is nothing to compare"
    assert "11650-04-03A-HANDED" in out


def test_a_part_that_is_not_in_the_job_is_said_out_loud(tmp_path, capsys):
    """--mirrors asked for 11650-04-03A because a hand named it. If the merge never created the
    base, silence would look identical to a base that inherited perfectly."""
    out = _run(tmp_path, [BASE, TWIN, ORPHAN], "--mirrors", capsys=capsys)
    assert "NOT IN THIS JOB: 11650-04-03A" in out
    assert "came from different runs" in out


def test_it_reads_a_job_whose_estimate_lives_under_estimate_summary(tmp_path, capsys):
    """Two document shapes are in circulation. A reader that knows one reports 'no such part'
    on every job of the other."""
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"estimate_summary": {"part_estimates": [BASE]}}), encoding="utf-8")
    tool.main(["11650-04-01A", "--json", str(path)])
    out = capsys.readouterr().out
    assert "rank 90" in out


def test_a_field_the_record_does_not_carry_is_not_a_field_with_no_source(tmp_path, capsys):
    """THREE STATES, NOT TWO. A costed record that had simply left provenance behind read
    exactly like an engine that never recorded any — and on 11650-04 that sent the diagnosis
    after a mirror rule that had, in fact, fired and written its provenance down."""
    no_source = dict(BASE)
    no_source.pop("material_source")
    out = _run(tmp_path, [no_source], "11650-04-01A", capsys=capsys)
    material_line = next(l for l in out.splitlines() if "normalized_material" in l)
    assert "carries no source for it" in material_line, (
        "the value is present and unattributed — that is not the same as absent")
    absent_line = next(l for l in out.splitlines() if "cut_length_mm" in l)
    assert "not on this record" in absent_line


def test_it_finds_a_fact_the_costed_record_keeps_under_another_key(tmp_path, capsys):
    """estimate_part builds a PROJECTION: the blank lives under material_estimate, not at the
    top. Reading only the top level reported '-- not set --' for a blank plainly on the sheet.
    The holder is named, so nobody has to trust that the search list is complete."""
    nested = dict(BASE)
    nested["material_estimate"] = {"blank_length_mm": 1250.0,
                                   "blank_length_mm_source": "dxf_flat_pattern"}
    out = _run(tmp_path, [nested], "11650-04-01A", capsys=capsys)
    blank_line = next(l for l in out.splitlines() if "blank_length_mm " in l)
    assert "1250.0 (material_estimate)" in blank_line
    assert "rank 80" in blank_line


def test_naming_nothing_is_an_error_not_an_empty_report(tmp_path):
    """A tool that prints a header and nothing else reads like a job with no parts."""
    path = _job(tmp_path, [BASE])
    with pytest.raises(SystemExit):
        tool.main(["--json", path])
