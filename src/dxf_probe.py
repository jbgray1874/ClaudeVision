"""What a DXF holds, read with ezdxf, reported as an inventory rather than an interpretation.

WHY THIS IS NOT A HANDWRITTEN PARSER ANY MORE. The first version of this module counted
group codes by hand, and review found four generic cases where it was simply wrong:

    a closed 10x10 polyline          perimeter 30 mm, not 40 — the closing segment was missed
    an arc, radius 10, 0 to 90 deg   extents 20 x 20, not 10 x 10 — it used the whole circle
    a Ø24 disc                       reported as "1 hole" — it is an outline, not a hole
    an image plus an inserted block  reported raster-only without looking inside the block

None of those is an unusual drawing; they are ordinary geometry. An audit that reports an
engine defect when the probe itself is wrong is worse than no audit, because it sends people
to fix things that are not broken. ezdxf is already a dependency of this codebase
(drawing_job_merge, dxf_reader) and handles all four correctly, so independence from the
production pipeline is achieved by not sharing its CODE — not by writing a second, worse
parser. Curve maths (bulges, splines, ellipses, arcs) is ezdxf's; this module only sums
straight segments between the vertices it returns.

AND IT NOW REPORTS AN INVENTORY, NOT A ROUTE. "circles: 2" is a fact about the file. "holes:
2" is a manufacturing interpretation, and a Ø24 disc proves it wrong — its outline is a
circle and it has no hole at all. Deciding which circles are holes needs the part's role,
its material and the drawing's instructions, which is the estimator's job and not this
module's. The same restraint applies to bend LINES on a bend layer: a count of lines is not
a count of bends.

UNITS ARE READ, NOT ASSUMED. $INSUNITS is decoded from the header; where it says inches the
measurements are converted and the conversion is stated, and where the file declares nothing
the numbers are published as unitless with `units_known` False. Labelling an inch drawing
"mm" produced comparisons that looked like defects and were arithmetic.

Anything ezdxf cannot measure is NAMED in `unsupported`, and any total computed while
something was skipped is marked `partial`. A partial sum published as a whole is how a
diagnostic becomes a liability.
"""
from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

# Layers SolidWorks writes fold lines to on an SDI flat export. Named, not guessed: every
# flat in the corpus carries exactly SLD-0 (profile) and BENDLINES (folds).
BEND_LAYERS = ("BENDLINES", "BEND", "BEND LINES", "BEND_LINES")

# Entities whose length and extents ezdxf can give us through a Path.
_MEASURABLE = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"}

_MM_PER_INCH = 25.4


def _unit_scale(doc: Any) -> tuple:
    """(scale to mm, unit name, is it known). Read from $INSUNITS, never assumed."""
    try:
        from ezdxf import units as _u
        code = doc.header.get("$INSUNITS", 0)
    except Exception:                                                    # noqa: BLE001
        return 1.0, "unstated", False
    if not code:
        # 0 means "unitless". A drawing that declares nothing is not thereby millimetres.
        return 1.0, "unstated", False
    try:
        name = str(_u.decode(code))
    except Exception:                                                    # noqa: BLE001
        name = f"code {code}"
    scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0,
             "in": _MM_PER_INCH, "ft": _MM_PER_INCH * 12.0}.get(name)
    if scale is None:
        return 1.0, name, False
    return scale, name, True


def _flat_entities(layout: Any, max_depth: int = 8) -> tuple:
    """(every entity with block references resolved, how deep we went, what we gave up on).

    An INSERT is a reference, not geometry — a file whose only visible content is a block
    containing the whole profile would otherwise look empty, and one holding an image next to
    an inserted block looked raster-only. ezdxf explodes them virtually, so nothing is
    modified on disk.

    RESOLUTION IS RECURSIVE, BECAUSE BLOCKS NEST. `virtual_entities()` explodes ONE level:
    an INSERT of a block that itself inserts the block holding the profile came back as
    another INSERT, and the old loop appended it as a leaf. A drawing built that way — which
    is the ordinary shape of a SolidWorks assembly export — reported `{"INSERT": 1}`, no
    circles and no outline length, while `ezdxf.bbox` (which recurses on its own) reported
    the real 100 x 50 extent. So the page showed an extent for geometry it also claimed did
    not exist, and the contradiction was on the audit's own side.

    The depth is capped and the cap is reported, not silent: a self-inserting block would
    otherwise recurse forever, and a total computed after abandoning a branch is a partial
    total that must say so.
    """
    out: List[Any] = []
    deepest = 0
    abandoned: List[str] = []

    def walk(entities: Any, depth: int, seen: tuple) -> None:
        nonlocal deepest
        deepest = max(deepest, depth)
        for entity in entities:
            if entity.dxftype() != "INSERT":
                out.append(entity)
                continue
            try:
                block_name = str(entity.dxf.name)
            except Exception:                                            # noqa: BLE001
                block_name = ""
            if depth >= max_depth:
                abandoned.append(f"{block_name or 'INSERT'} (deeper than {max_depth} levels)")
                out.append(entity)
                continue
            if block_name and block_name in seen:
                # A block that contains itself. Real files carry these by accident; following
                # one is an infinite descent, so it is named and left as a reference.
                abandoned.append(f"{block_name} (inserts itself)")
                out.append(entity)
                continue
            try:
                children = list(entity.virtual_entities())
            except Exception as err:                                      # noqa: BLE001
                abandoned.append(f"{block_name or 'INSERT'} ({type(err).__name__})")
                out.append(entity)
                continue
            walk(children, depth + 1, seen + ((block_name,) if block_name else ()))

    walk(layout, 0, ())
    return out, deepest, abandoned


def _path_length(entity: Any, sagitta: float = 0.01) -> Optional[float]:
    """Length via ezdxf's own flattening, so bulges and curves are ITS arithmetic not ours."""
    try:
        from ezdxf import path as _path
        points = list(_path.make_path(entity).flattening(distance=sagitta))
    except Exception:                                                    # noqa: BLE001
        return None
    if len(points) < 2:
        return None
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))



def _candidate_fold_axes(segments: List[tuple], gap_mm: float = 30.0,
                         tol_mm: float = 0.25) -> int:
    """How many distinct fold AXES the bend-layer segments describe. In millimetres.

    Not "bends", and the name is the claim. Two things this establishes and one it does not:

      IT DOES collapse a dashed fold. SDI's 117621702M draws ten 6mm dashes in two rows,
      describing two folds; counting entities reported ten.
      IT DOES keep folds drawn in opposite directions apart. A line's signed offset flips
      with its direction, which merged 117620202M's y=+124.12 and y=-124.12 and reported
      five bends as three. The direction is canonicalised into one half-plane first.
      IT DOES NOT establish that an axis is one manufacturing bend. Two separate tabs — or
      two nested parts — can fold on the same infinite line, and nothing here knows which
      profile owns which segment. Segments far apart along the axis are therefore counted
      separately, but the ownership question is open and the caller must not call the result
      a bend count.

    COORDINATES ARE CONVERTED BEFORE ANY TOLERANCE IS APPLIED. The tolerances below are
    millimetres. Applied to raw file coordinates they were whatever the file's units happened
    to be: on an inch drawing 0.25 meant 0.25 INCHES, and two folds a millimetre apart
    collapsed into one.
    """
    import math as _m
    axes: List[Dict[str, Any]] = []
    for (x1, y1), (x2, y2) in segments:
        dx, dy = x2 - x1, y2 - y1
        length = _m.hypot(dx, dy)
        if length <= 0:
            continue
        if dx < 0 or (abs(dx) <= 1e-9 and dy < 0):
            dx, dy = -dx, -dy
            x1, y1, x2, y2 = x2, y2, x1, y1
        angle = _m.degrees(_m.atan2(dy, dx)) % 180.0
        offset = (x1 * dy - y1 * dx) / length
        # position along the axis, so separated runs on one line stay separate
        ux, uy = dx / length, dy / length
        span = sorted((x1 * ux + y1 * uy, x2 * ux + y2 * uy))

        for axis in axes:
            if not ((abs(axis["angle"] - angle) <= 0.5
                     or abs(abs(axis["angle"] - angle) - 180.0) <= 0.5)
                    and abs(axis["offset"] - offset) <= tol_mm):
                continue
            # same infinite line — but only the same AXIS if the runs are close enough to be
            # dashes of one fold rather than two features that happen to line up
            if span[0] - axis["hi"] <= gap_mm and axis["lo"] - span[1] <= gap_mm:
                axis["lo"] = min(axis["lo"], span[0])
                axis["hi"] = max(axis["hi"], span[1])
                break
        else:
            axes.append({"angle": angle, "offset": offset, "lo": span[0], "hi": span[1]})
    return len(axes)


def probe_dxf(path_like: Any) -> Dict[str, Any]:
    """An inventory of what the file contains. Facts, with their limits stated."""
    name = Path(str(path_like)).name
    result: Dict[str, Any] = {
        "file": name, "readable": False, "reader": "ezdxf",
        "entity_counts": {}, "layers": [], "unsupported": [],
        "units": "unstated", "units_known": False,
        "entities_are_raster_only": False,
        "extent_length": None, "extent_width": None,
        "extent_is": "", "looks_like_flat_export": False,
        "blank_length_mm": None, "blank_width_mm": None,
        "circle_diameters": [], "circle_count": 0,
        "bend_layer_line_count": 0, "candidate_fold_axes": 0,
        "outline_length": None, "outline_length_partial": False,
        "text_values": [], "text_count": 0, "dimension_entities": 0,
        "block_nesting_depth": 0, "unresolved_blocks": [],
        "error": "",
    }
    try:
        import ezdxf
        import ezdxf.bbox
    except Exception as err:                                             # noqa: BLE001
        result["error"] = f"ezdxf unavailable: {err}"
        return result
    try:
        doc = ezdxf.readfile(str(path_like))
    except Exception as err:                                             # noqa: BLE001
        result["error"] = f"{type(err).__name__}: {err}"
        return result

    result["readable"] = True
    scale, unit_name, unit_known = _unit_scale(doc)
    result["units"] = unit_name
    result["units_known"] = unit_known

    msp = doc.modelspace()
    entities, block_depth, unresolved_blocks = _flat_entities(msp)
    result["block_nesting_depth"] = block_depth
    result["unresolved_blocks"] = unresolved_blocks
    counts: collections.Counter = collections.Counter()
    layers: set = set()
    texts: List[str] = []
    circles: List[float] = []
    bend_lines = 0
    bend_segments: List[tuple] = []
    profile: List[Any] = []
    unsupported: collections.Counter = collections.Counter()
    length_total = 0.0
    length_partial = False

    for entity in entities:
        kind = entity.dxftype()
        counts[kind] += 1
        try:
            layer = str(entity.dxf.layer)
        except Exception:                                                # noqa: BLE001
            layer = ""
        if layer:
            layers.add(layer)
        on_bend_layer = layer.strip().upper().replace("-", " ") in BEND_LAYERS

        if kind in ("TEXT", "MTEXT", "ATTRIB"):
            try:
                value = entity.plain_text() if hasattr(entity, "plain_text") \
                    else str(entity.dxf.text)
            except Exception:                                            # noqa: BLE001
                value = ""
            value = str(value).strip()
            if value:
                texts.append(value)
            continue
        if kind == "DIMENSION":
            continue
        if kind not in _MEASURABLE:
            if kind not in ("VIEWPORT", "ATTDEF"):
                unsupported[kind] += 1
            continue

        if on_bend_layer:
            bend_lines += 1
            if kind == "LINE":
                try:
                    # SCALED HERE, so the grouping tolerances below are millimetres and
                    # not whatever unit the file happens to use.
                    bend_segments.append((
                        (entity.dxf.start.x * scale, entity.dxf.start.y * scale),
                        (entity.dxf.end.x * scale, entity.dxf.end.y * scale)))
                except Exception:                                        # noqa: BLE001
                    pass
            continue

        if kind == "CIRCLE":
            try:
                circles.append(round(float(entity.dxf.radius) * 2 * scale, 3))
            except Exception:                                            # noqa: BLE001
                pass
        profile.append(entity)
        segment = _path_length(entity)
        if segment is None:
            length_partial = True
            unsupported[f"{kind} (length)"] += 1
        else:
            length_total += segment * scale

    result["entity_counts"] = dict(counts.most_common())
    result["layers"] = sorted(layers)
    result["dimension_entities"] = counts.get("DIMENSION", 0)
    result["bend_layer_line_count"] = bend_lines
    result["candidate_fold_axes"] = (
        _candidate_fold_axes(bend_segments) if bend_segments else (bend_lines or 0))
    result["circle_diameters"] = sorted(set(circles))
    result["circle_count"] = len(circles)
    # EVERY string, not a sample. The cap was 40 with no note, so a file with 64 MTEXT
    # entities silently lost 24 of them on a page claiming to elide nothing. Kept whole; a
    # count is carried so a reader can see at a glance how much there is.
    result["text_values"] = texts
    result["text_count"] = len(texts)
    # A block we could not descend into holds geometry we have not counted, so every total
    # drawn from this file is partial and says so by name.
    for block in unresolved_blocks:
        unsupported[f"block not resolved: {block}"] += 1
    if unresolved_blocks:
        length_partial = True
    result["unsupported"] = [f"{k} x{v}" for k, v in unsupported.most_common()]

    # RASTER-ONLY, DECIDED AFTER BLOCKS ARE RESOLVED. A file holding an image beside an
    # inserted block full of geometry is not an image-only file, and saying so sent the fix
    # in the wrong direction entirely.
    has_image = bool(counts.get("IMAGE") or counts.get("IMAGEDEF"))
    result["entities_are_raster_only"] = bool(has_image and not profile and not bend_lines)

    if length_total > 0:
        result["outline_length"] = round(length_total, 2)
        result["outline_length_partial"] = length_partial

    # EXTENTS FROM ezdxf, which knows an arc covers only its own sweep. The handwritten
    # version used the full circle's bounds and made a quarter-arc 20 x 20 instead of 10 x 10.
    try:
        box = ezdxf.bbox.extents(profile or entities, fast=False)
        if box.has_data:
            result["extent_length"] = round(box.size.x * scale, 2)
            result["extent_width"] = round(box.size.y * scale, 2)
    except Exception:                                                    # noqa: BLE001
        pass

    # A FLAT AND A DRAWING WEAR THE SAME EXTENSION AND THEIR EXTENTS MEAN DIFFERENT THINGS.
    # On a flat the profile extent IS the blank; on a GA it is the sheet border (10975's is
    # 1680 x 1074, which is no part). The test is deliberately weak-but-stated: no dimension
    # entities, no leaders, no title-block text. Absence of text does not PROVE a flat and a
    # real flat may carry an identification mark, so this is reported as a judgement, and the
    # blank is only offered where it holds.
    looks_flat = (result["dimension_entities"] == 0
                  and not texts
                  and counts.get("LEADER", 0) == 0
                  and bool(profile))
    result["looks_like_flat_export"] = looks_flat
    if result["extent_length"] is not None:
        if looks_flat and unit_known:
            result["blank_length_mm"] = result["extent_length"]
            result["blank_width_mm"] = result["extent_width"]
        elif looks_flat and not unit_known:
            result["extent_is"] = ("the file declares no units ($INSUNITS unset), so this "
                                   "extent is unitless and is NOT published as a blank")
        else:
            result["extent_is"] = ("the drawing sheet or border, NOT a part — this file has "
                                   "dimensions, leaders or title-block text")
    return result


def probe_many(paths: Any) -> List[Dict[str, Any]]:
    out = []
    for item in (paths or []):
        try:
            out.append(probe_dxf(item))
        except Exception as err:                                         # noqa: BLE001
            out.append({"file": Path(str(item)).name, "readable": False,
                        "error": f"{type(err).__name__}: {err}"})
    return out
