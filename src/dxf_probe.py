"""What a DXF actually holds, read from the file itself, independently of any reader.

THE AUDIT NEEDS A SOURCE OF TRUTH THAT IS NOT THE PIPELINE. source_drawing_data reports what
the summary holds, so it can only ever show what we already extract — and the question worth
answering is the opposite one: what is in the file that never reached a part?

    available in the file  ->  extracted  ->  assigned to the right part  ->  used in costing

Only the first of those can be established from outside, by opening the file and counting.
That is all this module does. It measures nothing the engine measures and prices nothing; it
exists so a claim like "the reader gets the blank" can be checked rather than believed.

Deliberately dependency-free, and deliberately not ezdxf: a DXF is a flat sequence of
group-code/value pairs and the handful of entities that matter here — LINE, CIRCLE, ARC,
LWPOLYLINE, MTEXT, DIMENSION, IMAGE — need no library to count. A probe that cannot run
because an import is missing tells you nothing on the machine where it matters.

AND IT DISTINGUISHES THE CASE THAT LOOKS THE SAME FROM OUTSIDE. A DXF can legitimately hold
nothing but a raster image; loading that through any API will not reveal geometry that is not
there. `entities_are_raster_only` says which of those two you have, so "the reader found no
geometry" can be separated from "there is no geometry to find".
"""
from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

# The layer SolidWorks writes fold lines to on an SDI flat export. Named, not guessed: all
# three flats in the corpus carry exactly SLD-0 (profile) and BENDLINES (folds).
BEND_LAYERS = ("BENDLINES", "BEND", "BEND LINES", "BEND_LINES")

_PROFILE_ENTITIES = ("LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE")


def _entities(path: Any) -> List[Dict[str, List[str]]]:
    """Every entity in the ENTITIES section as {group_code: [values]}, plus its type."""
    try:
        text = Path(path).read_bytes().decode("latin-1", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    out: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    inside = False
    index = 0
    while index < len(lines) - 1:
        code, value = lines[index].strip(), lines[index + 1].strip()
        if code == "2" and value == "ENTITIES":
            inside = True
        elif code == "2" and value in ("OBJECTS", "BLOCKS"):
            inside = False
        elif inside and code == "0":
            if current:
                out.append(current)
            current = {"type": value}
        elif inside and current is not None:
            current.setdefault(code, []).append(value)
        index += 2
    if current:
        out.append(current)
    return out


def _f(entity: Dict[str, Any], code: str, index: int = 0) -> Optional[float]:
    try:
        return float(entity[code][index])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def probe_dxf(path: Any) -> Dict[str, Any]:
    """Measure a DXF from its own entities. Returns facts, never opinions.

    Lengths are in the file's own units, which for every SDI export in the corpus is
    millimetres — the probe does not convert, because a unit it had to guess would be worse
    than one it reports plainly.
    """
    name = Path(str(path)).name
    result: Dict[str, Any] = {
        "file": name, "readable": False, "entity_counts": {}, "layers": [],
        "entities_are_raster_only": False,
        "blank_length_mm": None, "blank_width_mm": None,
        "extent_length_mm": None, "extent_width_mm": None,
        "looks_like_flat_export": False, "extent_is": "",
        "hole_diameters_mm": [], "hole_count": 0,
        "bend_line_count": 0, "text_values": [], "dimension_entities": 0,
        "cut_length_mm": None,
    }
    entities = _entities(path)
    if not entities:
        return result
    result["readable"] = True

    counts: collections.Counter = collections.Counter()
    layers: set = set()
    xs: List[float] = []
    ys: List[float] = []
    holes: List[float] = []
    bends = 0
    texts: List[str] = []
    cut = 0.0

    for entity in entities:
        kind = str(entity.get("type") or "")
        if kind in ("SECTION", "ENDSEC", "ENDBLK", "SEQEND"):
            continue
        counts[kind] += 1
        layer = (entity.get("8") or [""])[0]
        if layer:
            layers.add(layer)
        on_bend_layer = layer.strip().upper().replace("-", " ") in BEND_LAYERS

        if kind == "LINE":
            x1, y1, x2, y2 = (_f(entity, "10"), _f(entity, "20"),
                              _f(entity, "11"), _f(entity, "21"))
            if None not in (x1, y1, x2, y2):
                if on_bend_layer:
                    bends += 1
                else:
                    xs.extend([x1, x2])
                    ys.extend([y1, y2])
                    cut += math.dist((x1, y1), (x2, y2))
        elif kind == "CIRCLE":
            x, y, r = _f(entity, "10"), _f(entity, "20"), _f(entity, "40")
            if None not in (x, y, r) and r > 0:
                holes.append(round(2 * r, 3))
                xs.extend([x - r, x + r])
                ys.extend([y - r, y + r])
                cut += 2 * math.pi * r
        elif kind == "ARC":
            x, y, r = _f(entity, "10"), _f(entity, "20"), _f(entity, "40")
            start, end = _f(entity, "50"), _f(entity, "51")
            if None not in (x, y, r) and r > 0:
                xs.extend([x - r, x + r])
                ys.extend([y - r, y + r])
                if None not in (start, end):
                    sweep = (end - start) % 360.0
                    cut += 2 * math.pi * r * (sweep / 360.0)
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            px = [v for v in (entity.get("10") or [])]
            py = [v for v in (entity.get("20") or [])]
            pts = []
            for a, b in zip(px, py):
                try:
                    pts.append((float(a), float(b)))
                except (TypeError, ValueError):
                    continue
            if pts:
                if on_bend_layer:
                    bends += 1
                else:
                    xs.extend(p[0] for p in pts)
                    ys.extend(p[1] for p in pts)
                    cut += sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        elif kind in ("TEXT", "MTEXT"):
            for value in (entity.get("1") or []):
                cleaned = str(value).strip()
                if cleaned and not cleaned.startswith("{"):
                    texts.append(cleaned)

    result["entity_counts"] = dict(counts.most_common())
    result["layers"] = sorted(layers)
    result["dimension_entities"] = counts.get("DIMENSION", 0)
    result["bend_line_count"] = bends
    result["hole_diameters_mm"] = sorted(set(holes))
    result["hole_count"] = len(holes)
    result["text_values"] = texts[:40]
    # RASTER-ONLY IS A REAL CASE AND MUST NOT READ AS "the reader failed". No profile
    # geometry plus an image entity means there is nothing to extract, and no API will
    # reveal geometry a file does not contain.
    profile = sum(counts.get(k, 0) for k in _PROFILE_ENTITIES)
    result["entities_are_raster_only"] = bool(
        (counts.get("IMAGE") or counts.get("IMAGEDEF")) and profile == 0)
    # A FLAT EXPORT AND A DRAWING ARE DIFFERENT FILES WEARING THE SAME EXTENSION, AND THE
    # BOUNDING BOX MEANS DIFFERENT THINGS IN EACH.
    #
    # On a flat, the extent of the profile IS the blank: SDI's 117620202M measures
    # 1009.49 x 363.91 and that is what gets nested. On a GA export the same calculation
    # returns the SHEET — 10975_REV_B comes out 1680.00 x 1074.49, which is the drawing
    # border and no part at all. An earlier attempt of mine to recover part sizes from vector
    # geometry failed for exactly this reason: it measured the frame on every page and
    # returned one identical aspect ratio for six different parts.
    #
    # The tell is what a flat DOES NOT have. A SolidWorks flat export carries geometry and a
    # BENDLINES layer and nothing else — no dimension entities, no title-block text, no
    # leaders. So the blank is only reported where the file looks like a flat, and a drawing
    # reports its extent as a sheet size under its own name.
    looks_like_flat = (
        result["dimension_entities"] == 0
        and not texts
        and counts.get("LEADER", 0) == 0
        and counts.get("INSERT", 0) == 0
        and profile > 0)
    result["looks_like_flat_export"] = looks_like_flat
    if xs and ys:
        extent_l = round(max(xs) - min(xs), 2)
        extent_w = round(max(ys) - min(ys), 2)
        result["extent_length_mm"] = extent_l
        result["extent_width_mm"] = extent_w
        if looks_like_flat:
            result["blank_length_mm"] = extent_l
            result["blank_width_mm"] = extent_w
        else:
            result["extent_is"] = ("the drawing sheet or border, NOT a part — this file has "
                                   "dimensions/text/leaders, so it is a drawing export")
    if cut > 0:
        result["cut_length_mm"] = round(cut, 2)
    return result


def probe_many(paths: Any) -> List[Dict[str, Any]]:
    out = []
    for path in (paths or []):
        try:
            out.append(probe_dxf(path))
        except Exception as err:                                         # noqa: BLE001
            out.append({"file": Path(str(path)).name, "readable": False,
                        "error": f"{type(err).__name__}: {err}"})
    return out
