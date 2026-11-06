"""A flat cut from 2 mm and a flat cut from 5 mm are two articles, whatever their outline.

THE ESTIMATOR'S POINT: "not picking up 2/3 mm HIA acrylic — is it classing it as 5 mm". A
folder held `…_-01_2MM_…`, `…_-02_3MM_…` and five `…_5MM_…` flats of one part, and the sheet
nested everything at 5 mm.

TWO CAUSES, ONE CONTRACT.

  Flats were grouped by BOUNDING BOX alone, so "same outline" meant "same flat" — true of a
  revision re-exported, and equally true of the same profile cut from a different gauge. One
  member was kept per group and the rest discarded. Gauge and material are now part of what
  makes two flats one flat.

  A flat that matched no BOM child was minted as `<parent>-DXF<slug><index>` — a hashed key
  that cannot be looked up, quoted or matched to anything the shop holds, and which read as
  four products where the drawing has one part in several profiles. The drawing office has
  already numbered these: `…-01A_-07_…` is member 07 of 01A.

No job numbers and no part names below: the rules are about a filename convention, a gauge and
a material.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drawing_job_merge import (_orphan_child_pn, flat_stock_key,          # noqa: E402
                               _cluster_paths_by_bbox)

PARENT = {"part_number": "5555-01-02-01A"}


def _f(name):
    return Path(name)


def test_the_stock_key_is_the_gauge_and_the_material_the_name_states():
    assert flat_stock_key(_f("5555-01-02-01A_-01_2MM_High Impact Acrylic_RevA.DXF")) == \
        (2.0, "HIGH IMPACT ACRYLIC")
    assert flat_stock_key(_f("5555-01-02-01A_-02_3MM_High Impact Acrylic_RevA.DXF")) == \
        (3.0, "HIGH IMPACT ACRYLIC")
    assert flat_stock_key(_f("5555-01-02-04M_1.2MM_MS_RevA.DXF")) == (1.2, "MILD STEEL")


def test_two_gauges_under_one_stem_are_two_keys():
    """The whole of the estimator's complaint, stated as a rule."""
    a = flat_stock_key(_f("5555-01-02-01A_-01_2MM_High Impact Acrylic_RevA.DXF"))
    b = flat_stock_key(_f("5555-01-02-01A_-07_5MM_High Impact Acrylic_RevA.DXF"))
    assert a != b, "a 2 mm flat and a 5 mm flat are not the same article"


def test_two_files_of_one_gauge_and_material_are_one_key():
    """Several profiles of the same stock share one material line — they are one purchase."""
    a = flat_stock_key(_f("5555-01-02-01A_-06_5MM_High Impact Acrylic_RevA.DXF"))
    b = flat_stock_key(_f("5555-01-02-01A_-07_5MM_High Impact Acrylic_RevA.DXF"))
    assert a == b


def test_a_different_gauge_is_never_clustered_as_the_same_flat(monkeypatch):
    """THE LOSS ITSELF. Two flats with the SAME outline and different gauges must stay two
    clusters — otherwise one is picked and the other discarded, which is how a 2 mm part came
    to be nested as 5 mm."""
    import drawing_job_merge as m
    monkeypatch.setattr(m, "_dxf_bbox_wh", lambda _p: (770.0, 150.0))
    thin = _f("5555-01-02-01A_-01_2MM_High Impact Acrylic_RevA.DXF")
    thick = _f("5555-01-02-01A_-07_5MM_High Impact Acrylic_RevA.DXF")
    clusters = m._cluster_paths_by_bbox([thin, thick])
    assert len(clusters) == 2, "identical outlines, different stock — two flats"


def test_the_same_stock_and_outline_still_dedupes(monkeypatch):
    """THE BEHAVIOUR THIS MUST NOT BREAK. A revision re-exported is one flat, and that is what
    the bounding-box grouping was for."""
    import drawing_job_merge as m
    monkeypatch.setattr(m, "_dxf_bbox_wh", lambda _p: (770.0, 150.0))
    clusters = m._cluster_paths_by_bbox([
        _f("5555-01-02-01A_-07_5MM_High Impact Acrylic_RevA.DXF"),
        _f("5555-01-02-01A_-07_5MM_High Impact Acrylic_RevB.DXF"),
    ])
    assert len(clusters) == 1


def test_a_pack_whose_names_carry_no_gauge_is_unchanged(monkeypatch):
    """Backward compatible by construction: with no gauge and no material in either name both
    flats share the one empty key, and the outline decides exactly as it did before."""
    import drawing_job_merge as m
    monkeypatch.setattr(m, "_dxf_bbox_wh", lambda _p: (500.0, 200.0))
    clusters = m._cluster_paths_by_bbox([_f("PLAIN_ONE.DXF"), _f("PLAIN_TWO.DXF")])
    assert len(clusters) == 1


def test_an_unbound_flat_takes_the_number_the_drawing_office_gave_it():
    """NOT A HASHED KEY. `…-DXF12349026900` is not a part number: it cannot be looked up,
    quoted, or matched to anything the shop holds."""
    taken = set()
    assert _orphan_child_pn(PARENT, _f("5555-01-02-01A_-07_5MM_HIA_RevA.DXF"), 0, taken) == \
        "5555-01-02-01A-07"
    assert _orphan_child_pn(PARENT, _f("5555-01-02-01A_-01_2MM_HIA_RevA.DXF"), 1, taken) == \
        "5555-01-02-01A-01"


def test_no_synthesised_dxf_key_is_ever_produced():
    """The marker that put four unreadable rows on an estimate."""
    taken = set()
    for _i, _n in enumerate(("5555-01-02-01A_-07_5MM_HIA_RevA.DXF",
                             "5555-01-02-01A_5MM_HIA_RevA.DXF",
                             "NO_CONVENTION_AT_ALL.DXF")):
        assert "-DXF" not in _orphan_child_pn(PARENT, _f(_n), _i, taken)


def test_the_name_falls_back_through_things_a_person_wrote_down():
    """Member number, then the gauge the name states, then the position in the folder — each
    rung is evidence, and none of them is a hash."""
    taken = set()
    assert _orphan_child_pn(PARENT, _f("5555-01-02-01A_5MM_HIA_RevA.DXF"), 0, taken) == \
        "5555-01-02-01A-5MM"
    assert _orphan_child_pn(PARENT, _f("NO_CONVENTION_AT_ALL.DXF"), 4, taken) == \
        "5555-01-02-01A-05"


def test_two_flats_resolving_to_one_rung_do_not_collide():
    """A name that overwrote its sibling would lose a real part silently."""
    taken = set()
    a = _orphan_child_pn(PARENT, _f("5555-01-02-01A_5MM_HIA_RevA.DXF"), 0, taken)
    b = _orphan_child_pn(PARENT, _f("5555-01-02-01A_5MM_HIA_RevB.DXF"), 0, taken)
    assert a != b
