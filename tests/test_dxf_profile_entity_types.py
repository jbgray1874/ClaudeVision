"""A profile is a profile whichever entity type the exporter chose to draw it with.

The outline reader asks for LINE and ARC and nothing else. SolidWorks writes LINE + ARC,
which is why SDI's own packs never showed this — and why a customer's DXF would have.
Inventor, Solid Edge, most nesting software and nearly every hand-supplied DXF draw the
profile as one closed LWPOLYLINE.

Measured before the fix: a 200 x 100 plate with one hole came back

    blank 0.0 x 0.0, cut length 0, hole_count 1

because the hole counter walks polylines and the outline reader does not. Two readers of
one file disagreeing about what is in it, and the answer that reached costing was a part
with no size at all.

The conversion is virtual_entities(), not get_points(): a LWPOLYLINE carries BULGE values
for its arc segments, and reading vertices alone turns every filleted corner into a chord
— a quietly short cut length on a part that looks like it read fine.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ezdxf = pytest.importorskip("ezdxf")

from dxf_reader import extract_flat_pattern_data                    # noqa: E402

L, W = 200.0, 100.0
CUT = "SLD-0"


def _write(draw) -> Path:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4                                     # millimetres
    draw(doc.modelspace())
    path = Path(tempfile.mktemp(suffix=".dxf"))
    doc.saveas(str(path))
    return path


def _read(draw):
    path = _write(draw)
    try:
        return extract_flat_pattern_data(path) or {}
    finally:
        os.unlink(path)


def _lines(msp):
    for a, b in (((0, 0), (L, 0)), ((L, 0), (L, W)),
                 ((L, W), (0, W)), ((0, W), (0, 0))):
        msp.add_line(a, b, dxfattribs={"layer": CUT})


def _lwpolyline(msp):
    msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True,
                       dxfattribs={"layer": CUT})


def _polyline2d(msp):
    msp.add_polyline2d([(0, 0), (L, 0), (L, W), (0, W)], close=True,
                       dxfattribs={"layer": CUT})


@pytest.mark.parametrize("name,draw", [
    ("LINE segments", _lines),
    ("closed LWPOLYLINE", _lwpolyline),
    ("closed POLYLINE", _polyline2d),
])
def test_every_way_of_drawing_one_rectangle_measures_the_same(name, draw):
    out = _read(draw)
    assert (out.get("blank_length_mm"), out.get("blank_width_mm")) == (L, W), \
        f"a profile drawn as {name} did not measure as a {L:g} x {W:g} blank"
    assert abs((out.get("perimeter_mm") or 0) - 2 * (L + W)) < 0.01


def test_a_filleted_polyline_keeps_its_arcs():
    """The bulge case, which get_points() would silently chord.

    Filleted corners make the cut path LONGER than the chords across them, so a reader
    that drops bulges under-reads laser time on exactly the parts that have the most of
    it. The assertion is that the cut exceeds the square-cornered perimeter — chording
    would land it at or below.
    """
    def draw(msp):
        msp.add_lwpolyline(
            [(0, 0, 0, 0, 0.0), (L, 0, 0, 0, 0.2), (L, W, 0, 0, 0.0), (0, W, 0, 0, 0.2)],
            format="xyseb", close=True, dxfattribs={"layer": CUT})

    out = _read(draw)
    # 220, NOT 200. This asserted (L, W) when it was written, which encoded the very
    # defect found immediately afterwards: the bounding box was built from line endpoints
    # alone, so the outward bulges did not count towards the part's size. The plate is
    # genuinely 220 x 100 and the assertion was agreeing with the bug.
    assert out.get("blank_length_mm") == pytest.approx(220.0, abs=0.3)
    assert out.get("blank_width_mm") == pytest.approx(W, abs=0.3)
    assert (out.get("perimeter_mm") or 0) > 2 * (L + W), \
        "the fillet arcs were flattened to chords — bulges were dropped"


def test_the_outline_and_the_hole_counter_read_the_same_file():
    """The shape of the original defect: one reader saw a hole, the other saw nothing.

    A part with a hole and no size is not a small part, it is an unread one, and only the
    disagreement between the two counts made that visible.
    """
    def draw(msp):
        _lwpolyline(msp)
        msp.add_circle((50, 50), 5, dxfattribs={"layer": CUT})

    out = _read(draw)
    assert out.get("hole_count") == 1
    assert (out.get("blank_length_mm") or 0) > 0, \
        "the hole counter found geometry the outline reader could not"


# ── the zero that says why ──────────────────────────────────────────────────────────
def test_an_unmeasurable_profile_names_what_it_could_not_read():
    """Supporting SPLINE would fix one type and leave the next silent.

    Naming what was on the layer turns every unsupported type — including ones not
    written yet — into a stated refusal. A zero blank is indistinguishable from an empty
    file; a zero blank that names a SPLINE is something somebody can act on.
    """
    def draw(msp):
        msp.add_spline([(0, 0), (L, 0), (L, W), (0, W), (0, 0)],
                       dxfattribs={"layer": CUT})

    out = _read(draw)
    reasons = out.get("outline_unread_reasons") or []
    assert reasons, "a spline profile measured as zero and said nothing"
    assert "SPLINE" in " ".join(reasons)


def test_an_empty_file_does_not_claim_something_was_unread():
    """Absence and unreadability need different answers, and a reason attached to an
    empty file is noise in the place a real finding would appear."""
    out = _read(lambda msp: None)
    assert not (out.get("outline_unread_reasons") or [])


def test_a_readable_profile_carries_no_reason():
    out = _read(_lwpolyline)
    assert not (out.get("outline_unread_reasons") or [])



# ── the rule that had three spellings ───────────────────────────────────────────────
def test_a_cut_only_flat_cannot_rule_out_folding_by_any_route():
    """Reading a polyline profile made a latent bug fire, which is how it was found.

    Three separate places stripped `folding` on "flat pattern and zero bends". The 11350
    fix — an absent bend layer is silence, not a measured zero — was applied to ONE of
    them, and the copy that runs FIRST was not it. Nothing noticed, because a cut-only
    polyline flat previously produced no geometry at all, so flat_pattern_detected stayed
    False and none of the three branches could reach the part.

    All three now go through dxf_can_rule_out_folding.
    """
    from drawing_job_merge import apply_dxf_geometry_to_part, dxf_declares_bend_layer

    path = _write(lambda msp: msp.add_lwpolyline(
        [(0, 0), (258, 0), (258, 85), (0, 85)], close=True))
    try:
        assert dxf_declares_bend_layer(path) is False

        part = {"part_number": "11350-01-02",
                "operations": ["laser_cutting", "folding"],
                "textual_operations": ["folding"]}
        apply_dxf_geometry_to_part(part, path)

        assert part.get("flat_pattern_detected") is True, \
            "the polyline profile must be read — otherwise this proves nothing"
        assert "folding" in (part.get("operations") or []), \
            "a cut-only flat removed a fold the drawing states"
        assert "folding" in (part.get("textual_operations") or [])
    finally:
        os.unlink(path)


def test_a_declared_but_empty_bend_layer_still_rules_folding_out():
    """The other half of the rule, which must not be lost in guarding the first.

    A flat that DECLARES a bend layer and carries no lines on it has measured zero bends.
    That is a value, and it does rule out folding — a guard that refused both cases would
    let every phantom fold through.
    """
    from drawing_job_merge import apply_dxf_geometry_to_part

    def draw(msp):
        msp.doc.layers.add("BENDLINES")
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)

    path = _write(draw)
    try:
        part = {"part_number": "X", "operations": ["laser_cutting", "folding"],
                "textual_operations": ["folding"]}
        apply_dxf_geometry_to_part(part, path)

        assert "folding" not in (part.get("operations") or []), \
            "a measured zero must still remove a phantom fold"
        assert part.get("operations_ruled_out", {}).get("folding")
    finally:
        os.unlink(path)


def test_every_removal_of_folding_goes_through_the_shared_rule():
    """Three copies existed and one was corrected.

    Counting call sites is not enough — a fourth copy could be added tomorrow alongside
    them. What must hold is that no line REMOVES `folding` unless the shared rule has just
    authorised it, which is the property the 11350 fix was supposed to establish and did
    not.
    """
    import re as _re

    src_path = Path(__file__).resolve().parents[1] / "src" / "drawing_job_merge.py"
    lines = src_path.read_text(encoding="utf-8").splitlines()

    unguarded = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if not _re.search(r'!=\s*"folding"', line):
            continue
        window = "\n".join(lines[max(0, i - 14):i])
        if "dxf_can_rule_out_folding(" not in window and "_can_rule_out" not in window:
            unguarded.append(f"{src_path.name}:{i + 1}: {line.strip()}")

    assert not unguarded, (
        "a fold is removed without asking whether the DXF is entitled to rule it out — "
        "an absent bend layer is silence, not a measured zero:\n  "
        + "\n  ".join(unguarded))


# ── the blank is the extent of the WHOLE outline ────────────────────────────────────
def _bulged(b):
    def draw(msp):
        msp.add_lwpolyline(
            [(0, 0, 0, 0, 0.0), (L, 0, 0, 0, b), (L, W, 0, 0, 0.0), (0, W, 0, 0, b)],
            format="xyseb", close=True, dxfattribs={"layer": CUT})
    return draw


@pytest.mark.parametrize("bulge,expect_len", [(0.2, 220.0), (0.5, 250.0)])
def test_an_arc_that_reaches_past_the_straight_edges_is_part_of_the_blank(bulge, expect_len):
    """The bounding box was built from LINE endpoints alone.

    Every arc reaching beyond them was left out of the part's own size — a radiused nose,
    a rounded end, a D-shape, a bulged polyline edge. The plate below is genuinely
    220 x 100 and was reported 200 x 100: the blank comes back small, and a small blank is
    an under-priced one.
    """
    out = _read(_bulged(bulge))
    assert out.get("blank_length_mm") == pytest.approx(expect_len, abs=0.3), \
        "the outward arc was not counted in the blank extent"
    assert out.get("blank_width_mm") == pytest.approx(W, abs=0.3)


def test_the_abstain_gate_no_longer_throws_away_a_correct_area():
    """The second failure, caused by the first and worse than it.

    The reconstruction correctly found more material inside the outline than the (too
    small) bbox said existed, so fill came out above 100% — outside the plausibility band
    — and the gate discarded the CORRECT area and substituted the wrong bbox. A part with
    rounded ends was costed on its straight-edged shadow, twice over.
    """
    out = _read(_bulged(0.2))
    fill = out.get("bbox_fill_pct") or 0
    assert 30.0 <= fill <= 100.5, f"fill {fill}% is outside the band the gate accepts"
    assert out.get("blank_area_mm2") == pytest.approx(21343.9, rel=0.01), \
        "the polygonised area was replaced by the bounding box"


def test_a_disc_has_a_size():
    """No lines and no arcs, so the outline can only be the circle. Reading nothing gave
    a 0 x 0 blank on a perfectly measurable part.

    Only in that case: anywhere else a circle is a HOLE, and folding hole extents into the
    blank would be wrong in the other direction.
    """
    out = _read(lambda msp: msp.add_circle((0, 0), 60, dxfattribs={"layer": CUT}))
    assert out.get("blank_length_mm") == pytest.approx(120.0, abs=0.3)
    assert out.get("blank_width_mm") == pytest.approx(120.0, abs=0.3)


def test_a_hole_is_not_mistaken_for_the_outline():
    """The guard on the disc rule. A plate with a hole must measure the plate."""
    def draw(msp):
        _lwpolyline(msp)
        msp.add_circle((L / 2, W / 2), 5, dxfattribs={"layer": CUT})

    out = _read(draw)
    assert out.get("blank_length_mm") == pytest.approx(L, abs=0.3)


def test_the_arc_extent_and_the_area_use_one_flattening_tolerance():
    """Two tolerances would let the bbox and the reconstruction disagree about where the
    outline goes — which is precisely the disagreement that tripped the abstain gate."""
    src = (Path(__file__).resolve().parents[1] / "src" / "dxf_reader.py.py").read_text(
        encoding="utf-8-sig")
    assert src.count("0.20 / max(scale, 1e-9)") == 2, \
        "the flattening sagitta is no longer written the same way in both places"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
