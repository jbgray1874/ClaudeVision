"""F6: the phantom 792 x 760.3 — a GA sheet's border measured as a part's blank.

10975-02's pack holds one DXF: the GA drawing exported whole, with 9 DIMENSION entities,
a BOM table and the M&S title block. The reader returned flat_pattern_detected=True over
it, so drawing extents reached the record as a "measured flat" (confidence 1.0) and the
blank check reported a 377% disagreement against the model — twice — over geometry that
was never a part.

drawing_job_merge.drawing_export_reason has carried the decisive rule since 11350:
"DIMENSION entities are decisive: a flat pattern has none, ever." The reader that MAKES
the flat-pattern claim now applies the same rule, and the merge that lands geometry on
parts consults the claim instead of ignoring it.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest

ezdxf = pytest.importorskip("ezdxf")


def _flat_dxf(tmp: Path, with_dimension: bool = False) -> Path:
    d = ezdxf.new()
    d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 210.0, 760.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    if with_dimension:
        dim = msp.add_linear_dim(base=(0, -20), p1=(0, 0), p2=(L, 0))
        dim.render()
    p = tmp / ("with_dim.dxf" if with_dimension else "clean_flat.dxf")
    d.saveas(p)
    return p


def test_a_clean_flat_is_still_a_flat(tmp_path):
    from dxf_reader import extract_flat_pattern_data
    out = extract_flat_pattern_data(_flat_dxf(tmp_path))
    assert out.get("flat_pattern_detected") is True, \
        "the guard must not reject the real flats it exists to protect"


def test_a_dimensioned_drawing_is_not_a_flat(tmp_path):
    from dxf_reader import extract_flat_pattern_data
    out = extract_flat_pattern_data(_flat_dxf(tmp_path, with_dimension=True))
    assert out.get("flat_pattern_detected") is False, \
        "a DXF carrying DIMENSION entities is a drawing of the part, not its flat"


def test_the_merge_refuses_a_drawings_geometry_and_says_so(tmp_path):
    from dxf_reader import merge_dxf_into_scan_json
    scan = {"parts": [{"part_number": "10975-02-A01"}]}
    out = merge_dxf_into_scan_json(scan, _flat_dxf(tmp_path, with_dimension=True))
    part = out["parts"][0]
    assert not (part.get("normalized_geometry") or {}).get("dxf_augmented"), \
        "no border extents may land on the part as measured geometry"
    augs = out.get("dxf_augmentations") or []
    assert augs and "not a flat pattern" in str(augs[0].get("refused")), \
        "the file was seen and the refusal is on the record, not silent"
