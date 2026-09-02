r"""A blank that cannot contain its own cut path is not a small part. It is a wrong number.

Job 12392's back panel was recorded as a 16 x 3.7 mm blank carrying a 6,679 mm cut path —
six and a half metres of cutting inside a rectangle the size of a staple. It priced at
GBP 0.01. The sheet claimed 5,865 of them out of one 2500 x 1250, and the material total
for a steel panel job came to a few pounds.

Each number is perfectly plausible alone. Only the pair is impossible, and nothing was
comparing them, so the engine priced from the wrong one of the two and said nothing.

WHY THIS IS A MODULE. The invariant that reports it and the estimator that prices from it
must agree about what "impossible" means. A checker that blocks a job the pricer has
already costed at a hundredth of its value is not a check — it is a second opinion nobody
acted on, arriving after the money was written down.

THE DIRECTION OF SAFETY. This says a blank is impossible, never that it is right. A blank
that passes has not been verified; it has merely not been caught. Every caller must go on
treating an unverified dimension as unverified.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# The closest two cut lines can credibly run in sheet metal, in millimetres. A laser kerf
# is nearer 0.2mm, so this is generous by a factor of five on purpose: the test exists to
# catch a blank that is impossible, not one that is merely dense.
MIN_CREDIBLE_CUT_SPACING_MM = 1.0

# And then only complain at several times over. A long narrow strip is nearly all
# perimeter — 2500 x 2 has 5,004mm of outline in 5,000mm2 of room — so a bare "over one"
# would fire on geometry that is unusual rather than impossible. The cases this exists for
# clear the bar a hundredfold, so the margin costs nothing and buys the test the right to
# stop a price.
CUT_PATH_ABSURDITY_MARGIN = 3.0


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def cut_path_a_blank_could_hold_mm(length_mm: Any, width_mm: Any) -> Optional[float]:
    """The most cutting that fits in a blank before the lines are closer than a kerf.

    Area divided by the minimum credible spacing: a rectangle of L x W has room for
    roughly area/spacing millimetres of line before the cuts merge into each other.
    """
    length, width = _num(length_mm), _num(width_mm)
    if not length or not width:
        return None
    return (length * width) / MIN_CREDIBLE_CUT_SPACING_MM


def assess(length_mm: Any, width_mm: Any, cut_path_mm: Any) -> Dict[str, Any]:
    """Can this blank and this cut path both be true?

    Returns {'credible', 'evaluated', 'ratio', 'implied_spacing_mm', 'reason'}.

    `evaluated` is False when either number is missing — which is NOT a pass. A part with
    no cut path has not been shown to be consistent; it has not been asked.
    """
    length, width, cut = _num(length_mm), _num(width_mm), _num(cut_path_mm)
    if not length or not width or not cut:
        return {"credible": True, "evaluated": False, "ratio": None,
                "implied_spacing_mm": None,
                "reason": "no cut path or no blank recorded — nothing to compare"}

    room = cut_path_a_blank_could_hold_mm(length, width) or 0.0
    ratio = (cut / room) if room else float("inf")
    spacing = (length * width) / cut
    credible = ratio <= CUT_PATH_ABSURDITY_MARGIN
    if credible:
        return {"credible": True, "evaluated": True, "ratio": round(ratio, 2),
                "implied_spacing_mm": round(spacing, 4),
                "reason": "the cut path fits inside the blank"}
    return {
        "credible": False, "evaluated": True, "ratio": round(ratio, 1),
        "implied_spacing_mm": round(spacing, 4),
        "reason": (f"a {length:g} x {width:g} mm blank cannot hold a {cut:,.0f} mm cut path "
                   f"({ratio:.1f}x more than it could contain, implying cuts "
                   f"{spacing:.4f} mm apart)"),
    }


def is_credible(length_mm: Any, width_mm: Any, cut_path_mm: Any) -> bool:
    return bool(assess(length_mm, width_mm, cut_path_mm)["credible"])


# A cut path is only evidence when something MEASURED it. The PDF page reader sums every
# vector on the sheet — borders, views, dimension lines, leader lines, title block — and
# converts at 72 points to the inch with no drawing scale applied. On an A3 sheet that is
# thousands of millimetres of "cut path" belonging to the drawing, not the part, and on
# 12392 it was 6,679 mm against a part with no flat at all.
MEASURING_CUT_PATH_SOURCES = frozenset({
    "solidworks_api", "solidworks_flat_pattern", "dxf", "dxf_flat_pattern",
    "native", "estimator_confirmed", "knowledge_base",
    # A mirrored part's geometry is its twin's, measured. Rank 75 in source_precedence,
    # above every drawing read. Omitting it would have refused the measured blank on
    # every mirrored part in the system.
    "mirror_of_measured",
})

# Where a page-summed total lives. Named so it can be refused by name rather than by
# guessing from its value — a page sum and a real cut path are the same kind of number.
PAGE_SUMMED_CUT_PATH_KEYS = ("estimated_cut_length_mm",)


def cut_path_is_measured(source: Any) -> bool:
    """True when a cut path came from something that measured the PART.

    Deliberately a whitelist. A new reader that does not say what it is gets treated as
    unmeasured, which costs an unfired check; the reverse costs a priced wrong number.
    """
    return str(source or "").strip().lower() in MEASURING_CUT_PATH_SOURCES


# The size range a sheet fabrication's overall dimension can credibly take. Below this a
# number is a hole pitch, a radius, a gauge or a scale bar; above it, nothing SDI cuts.
MIN_SHEET_PART_MM = 10.0
MAX_SHEET_PART_MM = 4000.0


def plausible_as_a_sheet_part(length_mm: Any, width_mm: Any) -> bool:
    """Could these two numbers be the overall size of something we cut?

    This is what separates a blank nobody stamped but which is probably right — 120 x 80
    off a DXF merge that never recorded its source — from one that is plainly a feature
    dimension read as a part, like 12392's 16 x 3.7.

    Provenance alone could not make that distinction. Refusing every unstamped blank
    stopped a 120 x 80 bracket costing at all, on a part whose cut path fits it perfectly;
    accepting every unstamped blank is how the back panel priced at a penny.
    """
    length, width = _num(length_mm), _num(width_mm)
    if not length or not width:
        return False
    return all(MIN_SHEET_PART_MM <= v <= MAX_SHEET_PART_MM for v in (length, width))


def _stock_sheets_for(material: Any) -> Tuple[Tuple[float, float], ...]:
    """The sheet sizes this material is actually stocked in, from config."""
    try:
        import config
        sizes = getattr(config, "STANDARD_SHEET_SIZES_MM", {}) or {}
    except Exception:                                            # noqa: BLE001
        sizes = {}
    key = str(material or "").strip().upper()
    found = sizes.get(key) or sizes.get(key.replace(" ", "_")) or sizes.get("DEFAULT")
    out = []
    for pair in (found or ()):
        try:
            out.append((float(pair[0]), float(pair[1])))
        except Exception:                                        # noqa: BLE001
            continue
    return tuple(out)


def fits_a_stock_sheet(length_mm: Any, width_mm: Any, material: Any) -> Optional[bool]:
    """Could this blank be cut from any sheet this material comes in? None when we cannot say.

    THE ABSOLUTE BOUND ABOVE DOES NOT CATCH THE COMMON CASE. plausible_as_a_sheet_part asks
    only whether a number is between 10 mm and 4 m, so 12349-02's 2120 x 2120 sailed through
    — and 2120 x 2120 is not a gravity feeder, it is the drawing sheet's own bounding box,
    picked up as "the largest numbers in the document text".

    What made it visible is that Excel had already worked it out. Nothing 2120 square nests
    on a 2050 x 1520 acrylic sheet or a 2440 x 1220 board, so Qty Per Sheet came back empty,
    Cost Per Part came back empty, and the two largest parts on the job contributed NOTHING to
    the material total while appearing on the sheet as ordinary rows. A part that silently
    costs nothing is worse than one that is refused, because the refusal is at least visible.

    The same bounding box then went on to size the packaging and the haulage — 661 kg on two
    pallets — so one bad blank priced three lines.

    Rotation is allowed because a nester rotates. A material with no stock sizes of its own
    falls back to DEFAULT, because that is the sheet the NESTER falls back to — the answer has
    to be about the sheet this part will actually be costed on, not an ideal one. None only
    when there are no dimensions to test.
    """
    length, width = _num(length_mm), _num(width_mm)
    if not length or not width:
        return None
    sheets = _stock_sheets_for(material)
    if not sheets:
        return None
    part = (max(length, width), min(length, width))
    for sheet in sheets:
        if part[0] <= max(sheet) and part[1] <= min(sheet):
            return True
    return False


def largest_stock_sheet(material: Any) -> Optional[Tuple[float, float]]:
    """The biggest sheet this material comes in, so a refusal can say what it did not fit."""
    sheets = _stock_sheets_for(material)
    return max(sheets, key=lambda s: s[0] * s[1]) if sheets else None


def envelope_proves_it_never_leaves_the_plane(bbox_mm: Any, thickness_mm: Any) -> bool:
    """Is this part flat, on the evidence of its own bounding box?

    A box whose SMALLEST side is the material thickness has nothing folded, rolled or
    pressed out of plane — whatever the route says, and whatever the description calls it.
    12392's back panel carries `folding` in its operations and a 130 x 1435 x 1.5 envelope:
    the fold is a return along the sheet, not out of it, and the model proves it.

    This matters twice over, which is why it has a name instead of living inline:

      - it decides whether a drawing's printed overall may be read as a blank at all;
      - it decides whether a bounding box is the part's BLANK or merely a floor under it.

    Those two questions were being answered by the same arithmetic written out twice, and
    a rule with two spellings is a rule that will one day be corrected in one of them.
    """
    thickness = _num(thickness_mm)
    if not thickness:
        return False
    box = sorted([v for v in (_num(b) for b in (bbox_mm or [])) if v])
    if len(box) < 3:
        return False
    # Tolerance carries gauge rounding, not a different material: 0.3 mm absolute for thin
    # sheet, a quarter of the gauge for anything heavy enough that 0.3 is noise.
    return abs(box[0] - thickness) <= max(0.3, thickness * 0.25)


def blank_from_drawing_overalls(
    overall_length_mm: Any,
    overall_width_mm: Any,
    thickness_mm: Any,
    *,
    is_folded: bool = False,
    developed_length_mm: Any = None,
    bbox_mm: Any = None,
) -> Dict[str, Any]:
    """The blank a detail's printed overall size implies, or a refusal with its reason.

    Priority 2 of the sizing policy: when nothing measured a flat, the drawing's own
    overall size is a real number off a real detail, and pricing from it beats leaving a
    material gap. It is an INFERENCE — an overall describes the finished part — so it is
    returned marked, ranked below anything measured, and must stay visible as inferred
    everywhere it lands.

    THE GUARDRAILS ARE THE WHOLE POINT. Without them this becomes the failure it replaces:
    12392's back panel was "sized" at 16 x 3.7 by taking small plausible numbers off the
    sheet, and priced at a penny.

      - BOTH dimensions, or nothing. One number is not a blank.
      - THICKNESS REQUIRED. A sheet part with no thickness cannot be costed anyway, and
        demanding it rejects text scraped off a page that was never about this part.
      - PLAUSIBLE AS A SHEET PART. A dimension under 10mm or over 4m is not the overall
        size of a fabrication; it is a hole pitch, a radius, or a scale bar.
      - A FOLDED PART'S OVERALL IS NOT ITS BLANK. It unfolds longer. Refused unless a
        developed length is stated, or the bounding box proves the part never leaves the
        plane — a box whose smallest dimension is the material thickness has no fold out
        of plane, whatever the route says.
    """
    length, width = _num(overall_length_mm), _num(overall_width_mm)
    thickness = _num(thickness_mm)

    def _no(reason: str) -> Dict[str, Any]:
        return {"usable": False, "reason": reason, "blank_length_mm": None,
                "blank_width_mm": None, "source": None}

    if not length or not width:
        return _no("the detail does not print both an overall length and an overall width")
    if not thickness:
        return _no("no material thickness is stated, so an overall size cannot become a blank")
    for value, name in ((length, "length"), (width, "width")):
        if value < 10.0 or value > 4000.0:
            return _no(f"an overall {name} of {value:g} mm is not the size of a sheet "
                       f"fabrication — this is a feature dimension, not the part")

    if is_folded:
        developed = _num(developed_length_mm)
        if developed:
            return {"usable": True, "blank_length_mm": developed,
                    "blank_width_mm": min(length, width),
                    "source": "pdf_overall_dims",
                    "reason": (f"folded part sized from the stated developed length "
                               f"{developed:g} mm — inferred from drawing, confirm before "
                               f"a firm quote")}
        # A box whose smallest side IS the material has nothing folded out of plane.
        _box = sorted([v for v in (_num(b) for b in (bbox_mm or [])) if v])
        if envelope_proves_it_never_leaves_the_plane(bbox_mm, thickness):
            return {"usable": True, "blank_length_mm": max(length, width),
                    "blank_width_mm": min(length, width),
                    "source": "pdf_overall_dims",
                    "reason": (f"the route names folding, but the model's envelope is "
                               f"{_box[0]:g} mm deep — the material thickness — so nothing "
                               f"leaves the plane and the overall IS the blank. Inferred "
                               f"from drawing, confirm before a firm quote")}
        return _no("the part is folded and no developed length or flat pattern is stated — "
                   "an overall size understates a folded blank, so this needs a flat/DXF")

    return {"usable": True, "blank_length_mm": max(length, width),
            "blank_width_mm": min(length, width), "source": "pdf_overall_dims",
            "reason": (f"flat part sized from the detail's printed overall "
                       f"{max(length, width):g} x {min(length, width):g} x {thickness:g} mm "
                       f"— inferred from drawing, confirm before a firm quote")}


def better_blank_from(candidates: Tuple[Tuple[str, Any, Any], ...],
                      cut_path_mm: Any) -> Optional[Dict[str, Any]]:
    """The first candidate blank that could hold this cut path, with where it came from.

    Candidates are (source_name, length, width), offered in the order the caller trusts
    them. Used when a recorded blank has been shown impossible: a modelled bounding box
    understates a developed length and is a poor blank, but it is a defensible FLOOR, and
    a defensible floor beats a number already proven wrong by two orders of magnitude.

    Returns None when nothing offered survives — in which case the part has no blank we
    can stand behind, and saying so is the only honest answer left.
    """
    for name, length, width in candidates or ():
        if not (_num(length) and _num(width)):
            continue
        if is_credible(length, width, cut_path_mm):
            # NOT conditional on the pair having been evaluated. Requiring a verdict meant
            # a measured bounding box was refused whenever there was no cut path to test
            # it against — which is exactly the case it exists for, since a part with no
            # measured flat usually has no measured cut path either.
            return {"source": name, "blank_length_mm": _num(length),
                    "blank_width_mm": _num(width),
                    "assessment": assess(length, width, cut_path_mm)}
    return None
