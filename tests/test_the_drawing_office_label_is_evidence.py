"""A filename the drawing office typed on a laser export is an observation, not a guess.

    11650-04-01A_2MM PETG_REVG.DXF

That is not something the engine inferred. It is a deliberate label, applied by the person who
issued the flat, on the file the machine cuts from. It was ranked `inference` (20) AND applied
only into a gap — so on a part that already carried a material it was not recorded anywhere at
all.

WHAT THAT COST. 11650-04's pack says PETG four ways: the title block, an options list of
PETG-or-PC with no ABS anywhere, six exports across five revisions all named 2MM PETG, and 37
rows of plain PETG sheet in the parts catalogue. One SolidWorks model property said ABS and
won — and when the corroboration rule went looking for independent sources that disagreed with
it, the record held exactly one:

    normalized_material   ABS   the SolidWorks model  rank 90
        AGAINST IT: 1 independent source(s) said PETG — drawing_deterministic

The rule was right and had nothing to count. Everything else had been skipped rather than
submitted. An observation nobody writes down cannot corroborate anything.

RANKED WITH THE DRAWING TEXT, NOT ABOVE IT. A filename is as good as the convention behind it,
which is exactly what a title block is. It still loses on its own to a measured DXF or a
model. What changes is that it is now evidence — and two independent readings are what the
quorum is for. It also loses to the title block at equal rank, because a printed field on the
issued sheet beats a name on a file.

THE GAUGE IS THE SAME ARGUMENT AND THE SAME MONEY. The panels are costed at 2.2mm from a model
while every export says 2MM and the catalogue stocks 2.0 and 3.0 — so the rate lookup misses
on exactly the parts that matter, and a handed pair splits across two rate keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import source_precedence as sp  # noqa: E402
from source_precedence import apply_field, source_of, value_of  # noqa: E402

MATERIAL = "normalized_material"
GAUGE = "normalized_thickness_mm"


# ── the source exists and is ranked where it belongs ─────────────────────────────────

def test_it_ranks_with_the_drawing_and_not_with_a_guess():
    assert sp.rank("dxf_filename") == sp.rank("title_block") == 70
    assert sp.rank("dxf_filename") > sp.rank("inference")
    assert sp.rank("dxf_filename") < sp.rank("dxf")
    assert sp.rank("dxf_filename") < sp.rank("solidworks_api")


def test_it_is_not_claimed_as_a_measurement():
    """It is a name on a file. The waterfall's whole point is that a number off a model can
    be held against the model and a number off a label cannot — reports mark measured sources
    differently, and a label listed among them would read as geometry."""
    assert not sp.was_measured("dxf_filename")
    assert "dxf_filename" not in sp.MEASURED_SOURCES


def test_it_loses_to_the_title_block_at_equal_rank():
    """A printed field on the issued sheet beats a name on a file when the two disagree
    outright — the filename is the copy, the drawing is the original."""
    assert sp.tiebreak_priority("title_block") > sp.tiebreak_priority("dxf_filename")


def test_it_has_a_name_a_person_would_recognise():
    assert "filename" in sp.display_name("dxf_filename")


# ── it does the job it was promoted for ──────────────────────────────────────────────

def _side_panel():
    """11650-04-01A, in the order the readers run."""
    part = {}
    apply_field(part, MATERIAL, "PETG", "title_block")
    apply_field(part, MATERIAL, "ABS", "solidworks_api")
    return part


def test_the_model_alone_still_wins_before_the_export_is_read():
    part = _side_panel()
    assert value_of(part, MATERIAL) == "ABS"


def test_the_export_and_the_title_block_together_outvote_the_model():
    part = _side_panel()
    apply_field(part, MATERIAL, "PETG", "dxf_filename")
    assert value_of(part, MATERIAL) == "PETG"
    assert source_of(part, MATERIAL) == "dxf_filename"


def test_the_gauge_follows_the_same_route():
    """The rate lookup is per gauge: PETG at 2.0 has 37 catalogue rows and PETG at 2.2 has
    none, so a pair costed at two gauges cannot share a rate however the material resolves."""
    part = {}
    apply_field(part, GAUGE, 2.0, "title_block")
    apply_field(part, GAUGE, 2.2, "solidworks_api")
    assert value_of(part, GAUGE) == 2.2
    apply_field(part, GAUGE, 2.0, "dxf_filename")
    assert value_of(part, GAUGE) == 2.0


def test_the_reversal_is_written_down():
    part = _side_panel()
    apply_field(part, MATERIAL, "PETG", "dxf_filename")
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "OUTVOTED" in flags and "solidworks_api" in flags


# ── what it must not do ──────────────────────────────────────────────────────────────

def test_a_filename_on_its_own_does_not_overturn_a_model():
    """Otherwise every stale export in a job folder rewrites the material. 11650-04 has six
    revisions of one part sitting side by side."""
    part = {}
    apply_field(part, MATERIAL, "ABS", "solidworks_api")
    apply_field(part, MATERIAL, "PETG", "dxf_filename")
    assert value_of(part, MATERIAL) == "ABS"


def test_six_exports_of_one_part_are_one_observation():
    """REVC through REVG plus an unversioned copy: six files, one source, one reading. Counted
    six times a single naming convention would outvote anything on the job."""
    part = {}
    apply_field(part, MATERIAL, "ABS", "solidworks_api")
    for _ in range(6):
        apply_field(part, MATERIAL, "PETG", "dxf_filename")
    assert value_of(part, MATERIAL) == "ABS"


def test_it_does_not_displace_a_measured_dxf():
    """The geometry inside the file beats the name on the outside of it."""
    part = {}
    apply_field(part, MATERIAL, "ABS", "dxf")
    apply_field(part, MATERIAL, "PETG", "dxf_filename")
    assert value_of(part, MATERIAL) == "ABS"


# ── and the readers that produce it actually use it ──────────────────────────────────

def test_no_reader_still_files_a_filename_as_an_inference():
    """THE POINT WAS NEVER THE RANK TABLE. Adding a source nothing submits under would leave
    the record exactly as empty as before — 'built is not wired', in the module where that
    has already happened twice."""
    src = (Path(__file__).resolve().parents[1] / "src" / "drawing_job_merge.py").read_text(
        encoding="utf-8")
    for line in src.splitlines():
        if "material_from_dxf_filename" in line or "thickness_mm_from_dxf_filename" in line:
            continue
        if '_apply_field(' in line and '"inference"' in line and "_mat_fn" in line:
            pytest.fail(f"a filename is still submitted as an inference: {line.strip()}")
    assert '"dxf_filename")' in src, "nothing submits under the new source"


def test_the_filename_is_submitted_rather_than_gap_filled():
    """It was applied only when the part had NO material, so on the parts that matter — the
    ones a model has already written — it was never recorded at all."""
    src = (Path(__file__).resolve().parents[1] / "src" / "drawing_job_merge.py").read_text(
        encoding="utf-8")
    # NO CONDITION ON THE PART BEING EMPTY, at any of the sites. Asserting that `if _mat_fn:`
    # merely APPEARS passes while another site still gap-fills — there are three of them, and
    # a mutant that re-added the guard to one survived exactly that way.
    offenders = [ln.strip() for ln in src.splitlines()
                 if "_mat_fn and" in ln or ("_mat_fn" in ln and "normalized_material" in ln
                                            and "not part.get" in ln)]
    assert not offenders, (
        "a filename is still gap-filled rather than submitted: " + "; ".join(offenders))


def test_the_gauge_reader_submits_under_the_new_source_too():
    """The material was promoted and the gauge left behind on an earlier attempt. They are the
    same label on the same file, and 11650-04 splits on gauge as hard as on material."""
    src = (Path(__file__).resolve().parents[1] / "src" / "drawing_job_merge.py").read_text(
        encoding="utf-8")
    lines = [ln for ln in src.splitlines()
             if "_apply_field" in ln and "normalized_thickness_mm" in ln and "thk" in ln]
    assert lines, "nothing submits a filename gauge at all"
    for ln in lines:
        assert '"inference"' not in ln, f"filename gauge still filed as an inference: {ln.strip()}"
        assert '"dxf_filename"' in ln
