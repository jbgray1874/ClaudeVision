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
    assert (out.get("blank_length_mm"), out.get("blank_width_mm")) == (L, W)
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

if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
