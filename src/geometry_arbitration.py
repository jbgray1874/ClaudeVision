"""
geometry_arbitration.py — which measurement of a blank do we believe?

A part can arrive with two independent measurements of the same developed blank: the DXF
flat pattern, measured from the file, and the SolidWorks sheet-metal cut list, measured from
the model that produced that file. They should agree. When they do not, one of them is wrong,
and costing whichever happens to be checked first is how a part gets priced at half its size.

THE CASE THIS EXISTS FOR. A DXF exported mid-edit, or with its outer profile on a layer that
did not make it into the file, measures only the geometry present — a real number, produced
without error, and far too small. Job 12120's 04M measured 43.00 x 20.04mm against a model
flat of 60.00 x 34.04mm: 25% of the area, and it was costed. Nothing was broken; the file
simply did not contain the part.

THE RULE IS GEOMETRIC, NOT A LIST. It knows nothing about 04M, about job 12120, or about any
part number, filename or customer. It compares two areas and applies a tolerance, so a
drawing nobody has seen yet is held to exactly the same test.

The asymmetry is deliberate and physical:

  * A DXF MATERIALLY SMALLER than the model's flat is missing geometry. A developed blank
    cannot be smaller than the flat pattern the model develops — material is consumed going
    round a bend, never created. There is a sound fallback (the model), so the model wins.

  * A DXF MATERIALLY LARGER may be the drawing's extents rather than the profile, or a
    border that was measured with it. That is also a disagreement, but the DXF is still the
    only direct measurement of the file being cut, and swapping in the model would be
    trading one unverified number for another. The DXF is kept and the part is marked
    UNRECONCILED, so it reaches a human rather than a quote.

Neither branch invents a number. Both record what disagreed and by how much.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Two measurements of the same blank, from the same model. Ten per cent on area is already
# generous for that — it is the tolerance the engine's existing cross-check flagged on — and
# anything outside it is a disagreement about what the part IS, not measurement noise.
AREA_TOLERANCE = 0.10
# Area alone is not the blank. A 200 x 25 DXF and a 100 x 50 model flat have identical area
# and would "agree" — but they are different parts: different nesting on the sheet, different
# machine bed, different guillotine, possibly a different stock width entirely. Both SIDES
# have to agree, compared orientation-normalised (long against long, short against short) so
# a transposed export is not read as a disagreement.
DIMENSION_TOLERANCE = 0.10

DXF = "dxf"
NATIVE = "native"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") and f > 0 else None


def _sides_agree(dl: float, dw: float, nl: float, nw: float, tol: float) -> bool:
    """Long side against long side, short against short. Orientation is a drawing convention,
    not a fact about the part, so a transposed export must not read as a disagreement."""
    d_long, d_short = max(dl, dw), min(dl, dw)
    n_long, n_short = max(nl, nw), min(nl, nw)
    return (abs(d_long - n_long) <= tol * n_long
            and abs(d_short - n_short) <= tol * n_short)


def arbitrate_flat(dxf_length_mm: Any, dxf_width_mm: Any,
                   native_length_mm: Any, native_width_mm: Any,
                   area_tolerance: float = AREA_TOLERANCE,
                   dimension_tolerance: float = DIMENSION_TOLERANCE) -> Dict[str, Any]:
    """Decide which flat-pattern measurement to cost, and say why.

    Returns:
        winner          "dxf" | "native" | None (nothing to arbitrate)
        agree           True when the two are within tolerance
        unreconciled    True when they disagree and the DXF was kept anyway
        dxf_incomplete  True when the DXF measured materially less than the model
        area_ratio      dxf area / native area, or None
        reason          one sentence, quoting both measurements
    """
    dl, dw = _num(dxf_length_mm), _num(dxf_width_mm)
    nl, nw = _num(native_length_mm), _num(native_width_mm)
    have_dxf, have_native = bool(dl and dw), bool(nl and nw)

    if not have_dxf and not have_native:
        return {"winner": None, "agree": False, "unreconciled": False,
                "dxf_incomplete": False, "area_ratio": None,
                "reason": "no flat-pattern measurement from either source"}
    if not have_native:
        return {"winner": DXF, "agree": False, "unreconciled": False,
                "dxf_incomplete": False, "area_ratio": None,
                "reason": f"DXF flat {dl:g} x {dw:g}mm; no model flat to compare against"}
    if not have_dxf:
        return {"winner": NATIVE, "agree": False, "unreconciled": False,
                "dxf_incomplete": False, "area_ratio": None,
                "reason": f"model flat {nl:g} x {nw:g}mm; no DXF blank could be measured"}

    a_dxf, a_native = dl * dw, nl * nw
    ratio = a_dxf / a_native if a_native else None

    _sides_ok = _sides_agree(dl, dw, nl, nw, dimension_tolerance)
    if ratio is not None and abs(1.0 - ratio) <= area_tolerance and _sides_ok:
        return {"winner": DXF, "agree": True, "unreconciled": False,
                "dxf_incomplete": False, "area_ratio": round(ratio, 4),
                "reason": (f"DXF flat {dl:g} x {dw:g}mm agrees with the model flat "
                           f"{nl:g} x {nw:g}mm on both sides and to within "
                           f"{abs(1.0 - ratio) * 100:.1f}% on area")}

    if ratio is not None and abs(1.0 - ratio) <= area_tolerance and not _sides_ok:
        # Same area, different shape. Neither measurement is obviously the broken one, and
        # the difference matters to nesting, stock width and which machine can take it.
        return {"winner": DXF, "agree": False, "unreconciled": True,
                "dxf_incomplete": False, "area_ratio": round(ratio, 4),
                "reason": (f"DXF flat {dl:g} x {dw:g}mm and model flat {nl:g} x {nw:g}mm have "
                           f"the same AREA but different SIDES. Same area is not the same "
                           f"blank — it nests differently, may need different stock width and "
                           f"may not fit the same machine. UNRECONCILED")}

    if ratio is not None and ratio < 1.0:
        # Missing geometry. The model's flat is the only complete measurement available.
        return {"winner": NATIVE, "agree": False, "unreconciled": False,
                "dxf_incomplete": True, "area_ratio": round(ratio, 4),
                "reason": (f"DXF flat {dl:g} x {dw:g}mm is only {ratio * 100:.0f}% of the "
                           f"model flat {nl:g} x {nw:g}mm — a developed blank cannot be "
                           f"smaller than the flat it develops, so the DXF is missing "
                           f"geometry (commonly the outer profile). Costed from the model")}

    return {"winner": DXF, "agree": False, "unreconciled": True,
            "dxf_incomplete": False,
            "area_ratio": round(ratio, 4) if ratio is not None else None,
            "reason": (f"DXF flat {dl:g} x {dw:g}mm is {ratio * 100:.0f}% of the model flat "
                       f"{nl:g} x {nw:g}mm — larger than the model develops, which usually "
                       f"means drawing extents or a border were measured instead of the "
                       f"profile. The DXF is kept as the only direct measurement of the file, "
                       f"but the two are UNRECONCILED and must be confirmed")}
