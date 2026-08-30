"""No Shapely call may name an argument Shapely has renamed.

`Point(...).buffer(r, resolution=16)` sat on the LIVE measured-geometry path — src/
dxf_reader.py is a shim that loads dxf_reader.py.py, so the double-extension file is the
implementation, not a leftover. Shapely calls that parameter `resolution` in 1.x and
`quad_segs` in 2.x, and 2.1 deprecates the old spelling.

The deprecation itself is harmless. What it becomes is not: the call sits inside a
`try/except Exception: continue`, so on the release that removes the name it raises
TypeError, gets swallowed, and every hole silently stops being subtracted from net area.
No error, no flag, a quietly larger part on the rank-80 path.

Passing it positionally is correct on both majors — the second positional parameter has
always meant segments per quarter circle — and cannot rot.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# Names Shapely has renamed across a major version. Spelling either one binds the caller
# to a Shapely era; the positional form belongs to neither.
RENAMED = ("resolution", "quad_segs", "quadsegs")


def _buffer_calls():
    for path in sorted(SRC.rglob("*.py*")):
        if path.suffix not in (".py",) and not path.name.endswith(".py.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:                                           # pragma: no cover
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ".buffer(" in line:
                yield path, line_no, line


def test_no_buffer_call_names_a_renamed_shapely_argument():
    offenders = []
    for path, line_no, line in _buffer_calls():
        call = line[line.index(".buffer("):]
        for name in RENAMED:
            if re.search(rf"\b{name}\s*=", call):
                offenders.append(f"{path.relative_to(SRC.parent)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Shapely buffer() called with a version-bound argument name. Pass it positionally "
        "— the second positional parameter means segments per quarter circle on every "
        "Shapely version:\n  " + "\n  ".join(offenders))


def test_the_live_reader_is_the_double_extension_file():
    """If this ever stops being true, the check above is guarding the wrong file.

    src/dxf_reader.py is eleven lines of shim. The implementation — and the Shapely call —
    lives in dxf_reader.py.py, which reads as a leftover and is not.
    """
    shim = (SRC / "dxf_reader.py").read_text(encoding="utf-8-sig")
    assert "dxf_reader.py.py" in shim, \
        "dxf_reader.py no longer loads dxf_reader.py.py — re-point this guard"
    assert (SRC / "dxf_reader.py.py").is_file()


def test_the_hole_subtraction_is_still_inside_a_swallowing_except():
    """Why the guard above is a test rather than a comment.

    If this loop ever grows an honest error path, a broken buffer() call would announce
    itself and a static guard would be belt and braces. While the except swallows
    everything, it cannot, and the only warning is a number that quietly got bigger.
    """
    text = (SRC / "dxf_reader.py.py").read_text(encoding="utf-8-sig")
    block = text[text.index("for e in (cut_circs or []):"):]
    block = block[:block.index("fill = ")]
    assert "except Exception:" in block and "continue" in block



# ── what the positional argument MEANS ──────────────────────────────────────────────
# The guard above keeps the spelling out of the source. These pin the BEHAVIOUR, which is
# the thing that actually has to survive a Shapely upgrade: a rename is visible in a diff,
# a changed default or a changed argument ORDER is not.

def test_the_second_positional_argument_is_segments_per_quarter_circle():
    """Passing it positionally is only safe if the position means what the name meant.

    Measured rather than asserted from documentation: N yields exactly 4N vertices, which
    is the definition of segments-per-quarter-circle and could not hold by accident.
    """
    shapely = pytest.importorskip("shapely")
    from shapely.geometry import Point

    for n in (4, 8, 16, 64):
        ring = Point(0, 0).buffer(5.0, n).exterior
        assert len(ring.coords) - 1 == 4 * n, (
            f"buffer(r, {n}) produced {len(ring.coords) - 1} vertices, not {4 * n} — the "
            f"second positional argument no longer means quarter-circle segments")


def test_positional_and_the_current_keyword_are_the_same_call():
    shapely = pytest.importorskip("shapely")
    from shapely.geometry import Point

    a = Point(0, 0).buffer(5.0, 16)
    try:
        b = Point(0, 0).buffer(5.0, quad_segs=16)
    except TypeError:                                               # pragma: no cover
        pytest.skip("this Shapely predates quad_segs; positional is the portable form")
    assert a.equals(b) and a.area == b.area


def test_sixteen_segments_is_accurate_enough_to_cost_a_hole():
    """Why the value was not raised while the spelling was fixed.

    A 64-gon under-reads a circle by 0.16%. On a 10mm hole that is 0.13mm2 — and it errs
    by subtracting slightly LESS than the hole really removes, so the part comes out
    fractionally heavy rather than fractionally light. Wrong in the safe direction, and
    three orders of magnitude below anything an estimator would notice.
    """
    import math
    shapely = pytest.importorskip("shapely")
    from shapely.geometry import Point

    approx, exact = Point(0, 0).buffer(5.0, 16).area, math.pi * 25
    assert approx < exact, "the approximation must under-read, so holes are under-subtracted"
    assert abs(approx - exact) / exact < 0.002


# ── the same thing, through the reader that actually costs the part ─────────────────
def test_a_hole_is_actually_subtracted_from_the_blank_area():
    """The end-to-end version, and the one that would catch a swallowed TypeError.

    If the buffer call ever raises, the except around it returns the plate's FULL area and
    nothing says a hole was missed. That failure is invisible in every unit test of the
    Shapely call itself, because the Shapely call is not the thing that breaks — the
    handling around it is.
    """
    import math
    import os as _os
    import tempfile as _tf

    pytest.importorskip("shapely")
    ezdxf = pytest.importorskip("ezdxf")
    from dxf_reader import extract_flat_pattern_data

    L, W, R = 200.0, 100.0, 5.0
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True,
                       dxfattribs={"layer": "SLD-0"})
    msp.add_circle((L / 2, W / 2), R, dxfattribs={"layer": "SLD-0"})
    path = Path(_tf.mktemp(suffix=".dxf"))
    doc.saveas(str(path))
    try:
        out = extract_flat_pattern_data(path) or {}
    finally:
        _os.unlink(path)

    area = out.get("blank_area_mm2")
    exact = L * W - math.pi * R * R
    assert area is not None
    assert area < L * W, "the hole was not subtracted — the plate costed as solid"
    assert abs(area - exact) < 1.0, (
        f"net area {area} is not the plate minus its hole ({exact:.2f})")

if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
