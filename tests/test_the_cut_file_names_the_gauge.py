"""The CNC runs the DXF, so for GAUGE ONLY the cut file outranks the model.

WHY A TIEBREAK WAS NOT ENOUGH, WHICH IS THE CORRECTION THIS FIX RESTS ON. `FIELD_TIEBREAK`
orders the gauge readers — measured flat, then the file, then the name on it — and I described
gauge as "DXF-first" on the strength of it. It is not: `tiebreak_priority` is consulted only to
break a tie WITHIN one rank, by the observation display and the route claim sort.
`may_overwrite` never asks it. SolidWorks is 90 and every DXF source is 80 or 70, so they are
never at the same rank and that table could not reach the decision it was about. The model's
thickness won every time.

WHAT THAT COSTS. 12349-02's flats are named `2MM`, `3MM HIA`, `MS_3MM`, `6mm_MDF`. SolidWorks
holds 5 mm on 01A — a library default the estimator has already called wrong. Costing 5 where
the file cuts 2 changes the nest, the laser time and the weight: a different quote.

SCOPE, WHICH IS THE WHOLE POINT OF THE EXCEPTION BEING NARROW:

  * gauge only. Not material, not quantity, not a blank dimension.
  * a person still outranks everything.
  * no DXF, no change: the model stands exactly as before.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_precedence as sp                                          # noqa: E402

GAUGE = "normalized_thickness_mm"


def test_the_filename_gauge_displaces_the_models_library_default():
    """01A: the file says 2MM, SolidWorks says 5. The laser cuts 2."""
    part = {"part_number": "12349-02-69-01A"}
    assert sp.apply_field(part, GAUGE, 5.0, "solidworks_api")
    assert sp.apply_field(part, GAUGE, 2.0, "dxf_filename"), \
        "the cut file must be allowed to correct a library default"
    assert part[GAUGE] == 2.0
    assert sp.source_of(part, GAUGE) == "dxf_filename"


def test_the_measured_dxf_thickness_displaces_it_too():
    """The authorisation names "filename plus measured DXF thickness". In this tree the measured
    flat thickness is applied as plain `dxf` (drawing_job_merge:508), not `dxf_flat_pattern` —
    which is a geometry_source value and never the source of a thickness write. Both names are
    covered; this is the one that actually bites."""
    part = {"part_number": "12349-02-69-04M"}
    assert sp.apply_field(part, GAUGE, 5.0, "solidworks_api")
    assert sp.apply_field(part, GAUGE, 3.0, "dxf")
    assert part[GAUGE] == 3.0


def test_with_no_cut_file_the_model_stands():
    """This raises the DXF readers; it does not lower the model. A pack with no DXF is costed on
    the model exactly as it was, and a title block still loses to it."""
    for _weak in ("title_block", "drawing_deterministic", "bom_tree"):
        part = {"part_number": "12349-02-69-06A"}
        assert sp.apply_field(part, GAUGE, 5.0, "solidworks_api")
        assert not sp.apply_field(part, GAUGE, 1.2, _weak), f"{_weak} displaced the model"
        assert part[GAUGE] == 5.0
    # Deliberately one weak reader per part. Several weak readers AGREEING against the model is a
    # separate mechanism — corroboration_defends — which is reported and not exercised here.


def test_a_person_still_outranks_the_cut_file():
    """An estimator who knows the DXF is stale says so, and that is the end of it."""
    part = {"part_number": "12349-02-69-01A"}
    assert sp.apply_field(part, GAUGE, 2.0, "dxf_filename")
    assert sp.apply_field(part, GAUGE, 2.5, "estimator_confirmed")
    assert part[GAUGE] == 2.5


def test_material_is_not_touched_by_this():
    """NOT MATERIAL. The model's appearance already loses to the printed material at 68 against
    70, and the model's own material read still beats a filename. 8352's ply-vs-MDF rule is
    untouched, and a DXF filename does not get to rename the stock."""
    part = {"part_number": "12349-02-69-01A"}
    assert sp.apply_field(part, "normalized_material", "ACRYLIC", "solidworks_api")
    assert not sp.apply_field(part, "normalized_material", "MDF", "dxf_filename")
    assert part["normalized_material"] == "ACRYLIC"


def test_quantity_is_not_touched_by_this():
    """NOT QUANTITY. Quantity is the model's instance count in one quoted unit — the opposite of
    this exception, and the whole of the work that got the sheet reading it."""
    for _weak in ("dxf_filename", "dxf", "bom_tree", "drawing_deterministic"):
        part = {"part_number": "12349-02-69-100"}
        assert sp.apply_field(part, "quantity", 1, "solidworks_api")
        assert not sp.apply_field(part, "quantity", 3, _weak), f"{_weak} displaced the model"
        assert part["quantity"] == 1


def test_a_blank_dimension_is_not_touched_by_this():
    """Only gauge. A blank size is a different fact with a different answer, and the open
    model-versus-flat question above the ranks is deliberately still open."""
    part = {"part_number": "12349-02-69-01A"}
    assert sp.apply_field(part, "blank_length_mm", 600.0, "solidworks_api")
    assert not sp.apply_field(part, "blank_length_mm", 575.0, "dxf_filename")
    assert part["blank_length_mm"] == 600.0


def test_the_general_rank_table_is_unchanged():
    """The blanket flip was withdrawn. `rank` still answers the general question, which is what
    the route compiler and the reports ask it, and the exception lives in one field's override."""
    assert sp.rank("solidworks_api") == 90
    assert sp.rank("dxf") == 80
    assert sp.rank("dxf_filename") == 70
    assert sp.rank("bom_tree") == 60
    assert set(sp.FIELD_RANK_OVERRIDE) == {GAUGE}, \
        "one field. Widening this is a costing change and needs authorising"


def test_the_refusal_and_the_stamp_agree_about_the_order():
    """A DECISION TAKEN ON ONE ORDERING AND RECORDED UNDER ANOTHER is the defect that makes a
    provenance column worse than none. Every comparison in the resolver goes through field_rank,
    so the write, the refusal, the provenance and the flag all use the same order: a refused
    model value is flagged as losing, not as winning."""
    part = {"part_number": "12349-02-69-01A"}
    sp.apply_field(part, GAUGE, 2.0, "dxf_filename")
    sp.apply_field(part, GAUGE, 5.0, "solidworks_api")
    assert part[GAUGE] == 2.0
    assert sp.source_of(part, GAUGE) == "dxf_filename"
    _flags = " ".join(str(f) for f in (part.get("review_flags") or []))
    assert "5" in _flags and "solidworks" in _flags.lower(), \
        "what the cut file beat must be on the record"
    # And the observation survives whichever way round the two arrive.
    _obs = (part.get("_displaced") or {}).get(GAUGE) or []
    assert any(float(o.get("value")) == 5.0 for o in _obs if o.get("value") is not None)
