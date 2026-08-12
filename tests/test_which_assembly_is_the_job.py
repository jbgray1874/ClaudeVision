"""Which assembly is the job, and saying so when nothing could decide.

The top assembly's full-depth BOM becomes the job's component list, at rank 90. The rule for
choosing it was "the assembly record with the largest BOM" -- which on 11650's folder of
fifteen assemblies, released and scratch and test side by side, is a coin toss dressed as a
decision. A test rig containing more components than the GA would have supplied every
quantity on the sheet, silently, and the estimate would have reconciled perfectly against it.

THE STRUCTURAL FACT FIRST. Every SLDASM reports its own edges, so an assembly that appears as
somebody else's CHILD is by definition not the top of anything. That is exact, needs no naming
convention, and removes the common half of the failure -- a sub-assembly winning on size.

WHAT IT CANNOT DECIDE, IT SAYS. A scratch assembly is usually a root as well, and nothing in
the extract can rank two roots: that needs the job's own drawing numbers, which the picker is
not given. Size still breaks the tie, because a BOM chosen badly beats no BOM at all -- but
the run reports that a choice was made instead of presenting it as a reading.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from source_connectors.solidworks import _pick_top_assembly, SW_ASM, SW_PART   # noqa: E402


def _asm(title, bom_n, children=()):
    return {"doctype": SW_ASM, "title": title, "assembly_part_number": title,
            "bom": [{"part_number": f"{title}-{i}"} for i in range(bom_n)],
            "assembly_edges": [{"parent": title, "child": c} for c in children]}


def test_a_sub_assembly_never_wins_however_large_its_bom():
    """The common half, and it is exact. A full-depth BOM means a sub-assembly can easily
    list more components than its own parent's summary view."""
    top = _pick_top_assembly([_asm("11650-00-GA", 5, children=["11650-01-SA"]),
                              _asm("11650-01-SA", 40)])
    assert top["title"] == "11650-00-GA"


def test_two_roots_still_choose_but_record_that_they_chose():
    """A scratch assembly is nobody's child either. Nothing in the extract can rank it against
    the GA -- so the choice is made and declared, not hidden."""
    amb = {}
    # THE GA MUST OWN SOMETHING, or this extract records no tree at all and the roots test
    # passes vacuously — a different case with a different message, and the first version of
    # this fixture was in it without noticing.
    top = _pick_top_assembly([_asm("11650-00-GA", 12, children=["11650-01-SA"]),
                              _asm("11650-01-SA", 3),
                              _asm("11650-test assy", 30)], amb)
    assert top["title"] == "11650-test assy"          # size still breaks the tie
    assert amb["top_assembly_candidates"] == ["11650-00-GA", "11650-test assy"]
    assert "nobody's child" in amb["top_assembly_chosen_by"]


def test_a_single_root_is_not_reported_as_a_choice():
    """A warning raised on every job is a warning nobody reads."""
    amb = {}
    _pick_top_assembly([_asm("11650-00-GA", 5, children=["11650-01-SA"]),
                        _asm("11650-01-SA", 40)], amb)
    assert amb == {}


def test_an_extract_with_no_edges_falls_back_and_says_it_could_rule_nothing_out():
    """Older extracts carry no assembly_edges. Treating every assembly as a root would be
    silently wrong; treating none as one would return nothing at all."""
    amb = {}
    top = _pick_top_assembly([{"doctype": SW_ASM, "title": "A", "bom": [1, 2]},
                              {"doctype": SW_ASM, "title": "B", "bom": [1, 2, 3]}], amb)
    assert top["title"] == "B"
    assert "no assembly edges were recorded" in amb["top_assembly_chosen_by"]


def test_a_folder_of_parts_only_has_no_top_assembly():
    assert _pick_top_assembly([{"doctype": SW_PART, "title": "X", "bom": [1]}]) is None


def test_the_ambiguity_reaches_the_estimate_and_is_reported():
    """Built is not wired. A field recorded in the connector and read by nothing leaves the
    sheet presenting somebody's test rig as the job."""
    scan = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    inv = (_ROOT / "src" / "invariants.py").read_text(encoding="utf-8")
    assert '"top_assembly_candidates": _sw_job.meta.get("top_assembly_candidates")' in scan
    assert '"native_top_assembly_ambiguous", WARNING' in inv
    assert "every quantity on the sheet came from the wrong" in inv


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── the drawings already say which assembly this is ─────────────────────────────────
# 11650 proved roots-only insufficient. The only two assemblies that were nobody's child were
# "11650-test assy" and "Lock Assembly"; the released 11650-00-GA was neither, because the
# TEST RIG PARENTS IT. So the rule written to stop a sub-assembly winning excluded the right
# answer outright, size picked the test rig, and its list became the job at rank 90 -- TOP
# PANEL 1 -> 3, SIDE CHANNEL 2 -> 6, on a sheet an estimator would read as a measurement.
_JOB = ["11650-01-01M", "11650-02-01M", "11650-02-02M", "11650-03-02M", "11650-01-05A"]


def test_the_released_ga_wins_even_when_a_test_rig_contains_it():
    """The live shape, exactly. No naming convention and nothing about the word "test"."""
    # THE RIG IS NAMED SO IT SORTS FIRST. With the rig called "11650-test assy" this test
    # passed against a mutant that scored on RAW OVERLAP: both assemblies contain all five
    # job parts, so they tied, and the alphabetical tie-break happened to prefer the GA. Green
    # for a reason unrelated to the rule. A rig that wins the tie-break is the only fixture
    # that actually asks whether the extra scaffolding counts against it.
    recs = [
        {**_asm("11650-00-A TEST RIG", 0, children=["11650-00-GA"]),
         "bom": [{"part_number": c} for c in _JOB + ["JIG-01", "JIG-02", "FIXTURE"]]},
        {**_asm("11650-00-GA", 0), "bom": [{"part_number": c} for c in _JOB]},
        {**_asm("Lock Assembly", 0), "bom": [{"part_number": "LOCK-BODY"}]},
    ]
    amb = {}
    assert _pick_top_assembly(recs, amb, job_codes=set(_JOB))["title"] == "11650-00-GA"
    assert "the drawings name" in amb["top_assembly_chosen_by"]


def test_the_drawing_codes_actually_reach_the_picker():
    """Built is not wired. The whole fix is inert if file_scan never hands the job's own part
    numbers to the extract -- and a mutant that dropped the argument passed every behavioural
    test in this file, because they all call the picker directly."""
    scan = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    conn = (_ROOT / "src" / "source_connectors" / "solidworks.py").read_text(encoding="utf-8")
    assert "job_codes=_job_codes" in scan, "file_scan does not pass the drawing codes"
    assert "_pre_estimate_parts" in scan.split("_job_codes = ")[1][:400], \
        "the codes must come from the parts the drawings named, not from somewhere else"
    assert "normalize_native_extract(records, job_codes=job_codes)" in conn


def test_a_sub_assembly_does_not_win_on_precision_alone():
    """Jaccard, not raw overlap and not precision: a sub-assembly matches perfectly on the
    few parts it holds, and intersection-over-union is what refuses it."""
    recs = [
        {**_asm("11650-00-GA", 0), "bom": [{"part_number": c} for c in _JOB]},
        {**_asm("11650-02-SA01", 0),
         "bom": [{"part_number": "11650-02-01M"}, {"part_number": "11650-02-02M"}]},
    ]
    assert _pick_top_assembly(recs, {}, job_codes=set(_JOB))["title"] == "11650-00-GA"


def test_without_the_drawings_it_falls_back_to_the_structural_rule():
    """A job whose drawings named nothing still has to get an answer, and the roots rule is
    still the best available one."""
    recs = [{**_asm("11650-test assy", 0, children=["11650-00-GA"]),
             "bom": [{"part_number": c} for c in _JOB + ["JIG-01"]]},
            {**_asm("11650-00-GA", 0), "bom": [{"part_number": c} for c in _JOB]}]
    assert _pick_top_assembly(recs, {}, job_codes=None)["title"] == "11650-test assy"


def test_an_extract_for_another_job_entirely_does_not_hijack_the_choice():
    """Zero overlap must not silently select the best of a bad set -- it falls through to the
    structural rule, and the wrong-job guard downstream still gets its say."""
    recs = [{**_asm("12120-00-GA", 0), "bom": [{"part_number": "12120-01"}]}]
    amb = {}
    _pick_top_assembly(recs, amb, job_codes=set(_JOB))
    assert "the drawings name" not in (amb.get("top_assembly_chosen_by") or "")
