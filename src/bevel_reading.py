"""A bevel is read from the panel's own drawing; its flat outline only agrees (D-670).

12203-65-GA, 3 Nov 2026. Sheet 3/3 details the box's five panels and prints 45 degrees at
their edges. Each panel's DXF carries the bevel's inner edge as a second outline set in from
the first by the board's 10.8 mm. The merge read that second outline as a cut-through, so the
base became a 13,465 mm2 frame and the question "frame or step?" was asked of a solid panel.

AN INSET EQUAL TO THE THICKNESS PROVES NOTHING ON ITS OWN. A rebate, a pocket, an opening or
any other feature can sit at that inset. So the reading needs corroboration from the
drawing, and the outline only has to agree with it:

  * the panel's own sheet, or the sheet of the part its numbered flats were split from,
    prints a bevel angle whose run (thickness / tan angle) matches the inset, or prints the
    word BEVEL, MITRE or CHAMFER with an inset that matches 45 degrees;
  * every line inside the outline runs parallel to an outer edge, at that one inset,
    within max(0.5 mm, 10%) of the run;
  * the DXF layer of the inner lines, where it names a bevel, is recorded as support only.

With both, the panel is solid: its area is the outline's, its cut path is the outline, and
the bevelled edges are recorded as machining the CNC row must cover. Without the drawing's
word, nothing changes: the frame-or-step question stands, and it now says the inset also
reads as a bevel and what would confirm it. The model's own features are not read for
bevels yet, and the record says so.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_ANGLE_TEXT = re.compile(r"(?<![\d.])(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:°|º|DEG\b)", re.I)
_BEVEL_WORDS = re.compile(r"\b(?:BEVEL(?:LED|ED)?|MITRE[SD]?|MITER(?:ED|S)?|CHAMFER(?:ED|S)?)\b",
                          re.I)
_BEVEL_LAYER = re.compile(r"BEVEL|CHAMFER|MITRE|MITER", re.I)
FRAME_QUESTION = "nested_outline_frame_or_step"
MODEL_NOT_READ = "the model's features are not read for bevels"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f > 0 else None


def _tolerance(run: float) -> float:
    return max(0.5, 0.10 * run)


# ── what the flat's own lines say ──────────────────────────────────────────────────────

def _segments(path: Path) -> Optional[Tuple[List[Tuple[Tuple[float, float], Tuple[float, float], str]], bool]]:
    """Every straight segment in the flat's model space, with its layer; and whether anything
    curved was present. None when the file cannot be read."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(path))
    except Exception:                                                # noqa: BLE001
        return None
    segs: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []
    curved = False
    for e in doc.modelspace():
        kind = e.dxftype()
        layer = str(getattr(e.dxf, "layer", "") or "")
        if kind == "LINE":
            a, b = e.dxf.start, e.dxf.end
            segs.append(((float(a.x), float(a.y)), (float(b.x), float(b.y)), layer))
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            try:
                pts = [(float(p[0]), float(p[1])) for p in
                       (e.get_points("xy") if kind == "LWPOLYLINE" else
                        [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices])]
                closed = bool(e.closed if kind == "LWPOLYLINE" else e.is_closed)
            except Exception:                                        # noqa: BLE001
                return None
            for i in range(len(pts) - 1):
                segs.append((pts[i], pts[i + 1], layer))
            if closed and len(pts) > 2:
                segs.append((pts[-1], pts[0], layer))
        elif kind in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
            curved = True
    return segs, curved


def inner_offsets(path: Path, blank_long_mm: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """How far each line inside the outline sits from the outer edge it runs beside.

    {"insets_mm": [...], "outline_area_mm2", "outline_perimeter_mm", "bevelled_edge_mm",
     "edges": n, "layers": [...]} — or None when the flat holds no line inside its outline,
    something curved, or a line inside that is parallel to no outer edge."""
    got = _segments(Path(path))
    if not got:
        return None
    segs, curved = got
    if curved or len(segs) < 4:
        return None
    try:
        from shapely.geometry import LineString, Point
        from shapely.ops import polygonize, unary_union
    except Exception:                                                # noqa: BLE001
        return None
    lines = [LineString([a, b]) for a, b, _l in segs if a != b]
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        return None
    outline = unary_union(polys)
    if outline.geom_type != "Polygon":
        outline = max(getattr(outline, "geoms", [outline]), key=lambda g: g.area)
    exterior = outline.exterior
    minx, miny, maxx, maxy = outline.bounds
    scale = 1.0
    if blank_long_mm and max(maxx - minx, maxy - miny) > 0:
        scale = float(blank_long_mm) / max(maxx - minx, maxy - miny)
    ext_pts = list(exterior.coords)
    edges = [(ext_pts[i], ext_pts[i + 1]) for i in range(len(ext_pts) - 1)
             if ext_pts[i] != ext_pts[i + 1]]
    insets: List[float] = []
    layers: List[str] = []
    beside: Dict[int, bool] = {}
    for a, b, layer in segs:
        if a == b:
            continue
        mid = Point((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if exterior.distance(mid) * scale <= 0.05:
            continue                                   # on the outline itself
        if not outline.buffer(1e-6).contains(mid):
            return None                                # outside the outline: not this reading
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        best: Optional[Tuple[float, int]] = None
        for k, (p, q) in enumerate(edges):
            ex, ey = q[0] - p[0], q[1] - p[1]
            el = math.hypot(ex, ey)
            if el == 0 or abs(dx * ey - dy * ex) / (ln * el) > 0.02:
                continue                               # not parallel
            dist = abs((mid.x - p[0]) * ey - (mid.y - p[1]) * ex) / el
            if best is None or dist < best[0]:
                best = (dist, k)
        if best is None:
            return None                                # a line inside parallel to no edge
        insets.append(best[0] * scale)
        beside[best[1]] = True
        layers.append(layer)
    if not insets:
        return None
    bevelled = sum(math.hypot(edges[k][1][0] - edges[k][0][0], edges[k][1][1] - edges[k][0][1])
                   for k in beside) * scale
    return {"insets_mm": insets, "outline_area_mm2": outline.area * scale * scale,
            "outline_perimeter_mm": exterior.length * scale, "bevelled_edge_mm": bevelled,
            "edges": len(beside), "layers": sorted(set(layers))}


# ── what the drawing says ─────────────────────────────────────────────────────────────

def _sheet_text(sheets: Sequence[Mapping[str, Any]]) -> str:
    out = []
    for s in sheets:
        t = (s.get("pdfplumber_text") or s.get("normalized_text") or s.get("text")
             or s.get("page_text") or s.get("text_content") or "")
        if not str(t).strip():
            try:
                from detail_page_geometry import read_sheet_figures
                t = read_sheet_figures(s).get("text") or ""
            except Exception:                                        # noqa: BLE001
                t = ""
        out.append(str(t))
    return "\n".join(out)


def _parent_of(part: Mapping[str, Any], by_pn: Mapping[str, Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The part whose numbered flats this panel was split from: its record names it, else its
    code is that part's followed by a piece number."""
    named = str(part.get("dxf_flat_of_parent") or part.get("dxf_minted_piece_of") or "").upper()
    if named and named in by_pn:
        return by_pn[named]
    pn = str(part.get("part_number") or "").upper()
    m = re.match(r"^(.*[A-Z])-(\d{1,2})$", pn)
    if m and part.get("dxf_orphan") and m.group(1) in by_pn:
        return by_pn[m.group(1)]
    return None


# ── a callout belongs to the panel whose detail it sits in ──────────────────────────────
#
# A sheet that details several panels (12203-65-01J's sheet 3/3 draws all five, each under its
# balloon) carries several panels' callouts, possibly at different angles. A callout is this
# panel's only where it sits nearer this panel's balloon than any other, and that balloon's
# area also carries one of this panel's own sizes (D-671 review).

_TOKEN_CACHE: Dict[Tuple[str, float, int], Optional[Dict[str, Any]]] = {}
_BALLOON = re.compile(r"^\d{1,2}$")
_ANGLE_WORD = re.compile(r"^(\d{1,2}(?:[.,]\d{1,2})?)\s*[°º]$")
_FIGURE_WORD = re.compile(r"^\d{2,4}(?:[.,]\d{1,2})?$")


def _ringed(points: Sequence[Tuple[float, float]], cx: float, cy: float) -> bool:
    """A lone number inside a ring: twelve or more drawn points at one radius (within 15%)
    of 5 to 30 points around it. A circle drawn as curves or as many short lines both pass;
    a table cell's four corners do not."""
    ds = sorted(math.hypot(px - cx, py - cy) for px, py in points
                if abs(px - cx) < 40 and abs(py - cy) < 40)
    ds = [d for d in ds if d > 2.0]
    if len(ds) < 12:
        return False
    med = ds[len(ds) // 2]
    return 5.0 <= med <= 30.0 and sum(1 for d in ds if abs(d - med) <= 0.15 * med) >= 12


def page_tokens(sheet: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """{"balloons": {n: (x, y)}, "angles": [(deg, x, y)], "figures": [(mm, x, y)],
    "words": [(WORD, x, y)]} read off a sheet's PDF page, or None without the PDF."""
    import os
    path = str(sheet.get("source_pdf_path") or "")
    try:
        from detail_page_geometry import _local_page_number
        local = _local_page_number(sheet)
        key = (path, os.path.getmtime(path), int(local or 0))
    except Exception:                                                # noqa: BLE001
        return None
    if key in _TOKEN_CACHE:
        return _TOKEN_CACHE[key]
    out: Optional[Dict[str, Any]] = None
    try:
        import fitz                                                  # noqa: WPS433
        doc = fitz.open(path)
        try:
            if 0 < key[2] <= doc.page_count:
                pg = doc.load_page(key[2] - 1)
                pts: List[Tuple[float, float]] = []
                for d in pg.get_drawings():
                    for it in d.get("items") or []:
                        for q in it[1:]:
                            if hasattr(q, "x") and hasattr(q, "y"):
                                pts.append((float(q.x), float(q.y)))
                            elif hasattr(q, "x0"):
                                pts += [(float(q.x0), float(q.y0)), (float(q.x1), float(q.y1))]
                out = {"balloons": {}, "angles": [], "figures": [], "words": []}
                for w in pg.get_text("words") or []:
                    x, y, word = (w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0, str(w[4]).strip()
                    m = _ANGLE_WORD.match(word)
                    if m:
                        out["angles"].append((float(m.group(1).replace(",", ".")), x, y))
                    elif _BALLOON.match(word) and _ringed(pts, x, y):
                        out["balloons"].setdefault(int(word), (x, y))
                    elif _FIGURE_WORD.match(word):
                        out["figures"].append((float(word.replace(",", ".")), x, y))
                    if _BEVEL_WORDS.fullmatch(word.strip(".,:;")):
                        out["words"].append((word.strip(".,:;").upper(), x, y))
        finally:
            doc.close()
    except Exception:                                                # noqa: BLE001
        out = None
    _TOKEN_CACHE[key] = out
    return out


_CHAIN_GAP_PT = 250.0


def detail_areas(tok: Mapping[str, Any]) -> Dict[Tuple[str, int], int]:
    """Which balloon's detail each figure, angle and word belongs to: grown from the balloons
    through the nearest token each time (single linkage), so a callout joins the detail whose
    figures it sits among, not merely the nearest balloon. A token further than 250 pt from
    every detail joins none."""
    toks: List[Tuple[str, int, float, float]] = []
    for kind in ("figures", "angles", "words"):
        for i, t in enumerate(tok.get(kind) or []):
            toks.append((kind, i, float(t[1]), float(t[2])))
    held: List[Tuple[float, float, int]] = [(x, y, n) for n, (x, y) in (tok.get("balloons") or {}).items()]
    out: Dict[Tuple[str, int], int] = {}
    free = list(toks)
    while free and held:
        best = None
        for j, (kind, i, x, y) in enumerate(free):
            for hx, hy, n in held:
                d = math.hypot(hx - x, hy - y)
                if best is None or d < best[0]:
                    best = (d, j, n)
        if best is None or best[0] > _CHAIN_GAP_PT:
            break
        _d, j, n = best
        kind, i, x, y = free.pop(j)
        out[(kind, i)] = n
        held.append((x, y, n))
    return out


def panel_cell_evidence(sheets: Sequence[Mapping[str, Any]], piece_no: int,
                        sizes: Sequence[float]) -> Dict[str, Any]:
    """The angles and bevel words in piece `piece_no`'s own detail on a sheet of several:
    tokens in the detail grown from its balloon, on a page where that detail also carries one
    of its own sizes. {"angles", "words", "pages", "how"}."""
    angles: set = set()
    words: set = set()
    pages: List[Any] = []
    seen_balloon = False
    for sheet in sheets:
        tok = page_tokens(sheet)
        if not tok or piece_no not in tok["balloons"]:
            continue
        seen_balloon = True
        area = detail_areas(tok)
        own_size = any(area.get(("figures", i)) == piece_no and
                       any(abs(v - s) <= max(0.5, 0.005 * s) for s in sizes if s)
                       for i, (v, x, y) in enumerate(tok["figures"]))
        if not own_size:
            continue
        pages.append(sheet.get("page_number"))
        angles |= {a for i, (a, x, y) in enumerate(tok["angles"])
                   if 5.0 < a < 85.0 and area.get(("angles", i)) == piece_no}
        words |= {w for i, (w, x, y) in enumerate(tok["words"])
                  if area.get(("words", i)) == piece_no}
    how = (f"balloon {piece_no}'s own detail (page {', '.join(str(p) for p in pages)}), which "
           f"carries this panel's own size" if pages else
           (f"balloon {piece_no} is drawn, but no area of it carries this panel's own size"
            if seen_balloon else
            f"no balloon {piece_no} on the sheet ties a callout to this panel"))
    return {"angles": sorted(angles), "words": sorted(words), "pages": pages, "how": how}


def _piece_number(part: Mapping[str, Any]) -> Optional[int]:
    """The number its flat's name gives it, else the number its code ends in."""
    path = _flat_path(part)
    if path is not None:
        try:
            from drawing_job_merge import member_number_from_filename
            n = member_number_from_filename(path)
            if n:
                return int(n)
        except Exception:                                            # noqa: BLE001
            pass
    m = re.search(r"-(\d{1,2})$", str(part.get("part_number") or ""))
    return int(m.group(1)) if m else None


def drawing_evidence(part: Mapping[str, Any], summary: Mapping[str, Any],
                     by_pn: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """{"angles": [...], "words": [...], "pages": [...], "whose": code, "how": sentence} from
    the panel's own sheet; else from ITS OWN DETAIL on the sheet of the part it was split
    from, never from that sheet as a whole."""
    empty = {"angles": [], "words": [], "pages": [], "whose": "", "how": "no sheet"}
    try:
        from detail_page_geometry import own_sheets
    except Exception:                                                # noqa: BLE001
        return empty
    sheets = own_sheets(part, summary)
    if sheets:
        text = _sheet_text(sheets)
        return {"angles": sorted({float(a.replace(",", ".")) for a in _ANGLE_TEXT.findall(text)
                                  if 5.0 < float(a.replace(",", ".")) < 85.0}),
                "words": sorted({w.upper() for w in _BEVEL_WORDS.findall(text)}),
                "pages": [s.get("page_number") for s in sheets],
                "whose": str(part.get("part_number") or ""), "how": "its own sheet"}
    parent = _parent_of(part, by_pn)
    if parent is None:
        return empty
    psheets = own_sheets(parent, summary)
    n = _piece_number(part)
    if not psheets or not n:
        return {**empty, "whose": str(parent.get("part_number") or ""),
                "how": "no piece number ties it to a detail on its part's sheet"}
    sizes = [_num(part.get("overall_length_mm")) or 0.0, _num(part.get("overall_width_mm")) or 0.0]
    cell = panel_cell_evidence(psheets, n, sizes)
    return {**cell, "whose": str(parent.get("part_number") or "")}


def _flat_path(part: Mapping[str, Any]) -> Optional[Path]:
    """The flat file the part was measured from: the first recorded path that exists."""
    orphan = part.get("dxf_orphan") if isinstance(part.get("dxf_orphan"), Mapping) else {}
    for cand in (part.get("dxf_source_file"), part.get("dxf_path"), orphan.get("path")):
        if cand and Path(str(cand)).is_file():
            return Path(str(cand))
    return None


def read_bevel(part: Mapping[str, Any], summary: Mapping[str, Any],
               by_pn: Mapping[str, Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The bevel this panel's drawing states and its flat agrees with, or the reasons it is not
    taken: {"taken": bool, ...}. None when the flat holds no line inside its outline."""
    t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    path = _flat_path(part)
    if not t or not path:
        return None
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), Mapping) else {}
    long_mm = _num(ng.get("blank_length_mm")) or _num(part.get("overall_length_mm"))
    geo = inner_offsets(path, long_mm)
    if not geo:
        return None
    ins = geo["insets_mm"]
    mid = sorted(ins)[len(ins) // 2]
    ev = drawing_evidence(part, summary, by_pn)
    support = [lyr for lyr in geo["layers"] if _BEVEL_LAYER.search(lyr)]
    found = None
    for ang in ev["angles"]:
        run = t / math.tan(math.radians(ang))
        if all(abs(x - run) <= _tolerance(run) for x in ins):
            found = {"angle_deg": ang, "run_mm": round(run, 2),
                     "because": f"its sheet prints {ang:g} degrees, a run of {run:.1f} mm "
                                f"at {t:g} mm thick"}
            break
    if found is None and ev["words"] and all(abs(x - t) <= _tolerance(t) for x in ins):
        found = {"angle_deg": 45.0, "run_mm": round(t, 2),
                 "because": f"its sheet says {', '.join(ev['words'])} and prints no angle; "
                            f"the inset matches 45 degrees at {t:g} mm thick"}
    base = {"inset_mm": round(mid, 2), "insets_mm": [round(x, 2) for x in ins],
            "thickness_mm": t, "sheet_of": ev["whose"], "pages": ev["pages"],
            "angles_printed": ev["angles"], "words_printed": ev["words"],
            "evidence_from": ev.get("how"),
            "layer_support": support, "model": MODEL_NOT_READ, **geo}
    if found:
        return {"taken": True, **base, **found}
    return {"taken": False, **base}


# ── applying it ───────────────────────────────────────────────────────────────────────

def _solid(part: Dict[str, Any], got: Mapping[str, Any]) -> None:
    """The panel is solid: its area and weight are the outline's, its cut path the outline."""
    area = float(got["outline_area_mm2"])
    raw = part.get("dxf_raw_geometry") if isinstance(part.get("dxf_raw_geometry"), dict) else None
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), dict) else None
    band = _num((raw or {}).get("blank_area_mm2")) or _num((ng or {}).get("blank_area_mm2"))
    factor = (area / band) if band else None
    if raw is not None:
        raw["blank_area_mm2"] = area
        raw["estimated_cut_length_mm"] = float(got["outline_perimeter_mm"])
        if factor and _num(raw.get("weight_kg")):
            raw["weight_kg"] = float(raw["weight_kg"]) * factor
        raw["bevel_lines_not_cut"] = True
    if ng is not None:
        ng["blank_area_mm2"] = area
        ng["perimeter_mm"] = float(got["outline_perimeter_mm"])
        for k in ("weight_kg", "weight_g"):
            if factor and _num(ng.get(k)):
                ng[k] = float(ng[k]) * factor
    if factor:
        for k in ("dxf_weight_g", "dxf_weight_kg"):
            if _num(part.get(k)):
                part[k] = float(part[k]) * factor


def apply_bevel_readings(parts: Iterable[Any], summary: Mapping[str, Any]) -> List[str]:
    """Read each flat's inner lines against its drawing; returns the codes taken as bevelled."""
    plist = [p for p in (parts or []) if isinstance(p, dict)]
    by_pn = {str(p.get("part_number") or "").upper(): p for p in plist if p.get("part_number")}
    taken: List[str] = []
    for part in plist:
        if part.get("bevel_reading"):
            continue
        try:
            got = read_bevel(part, summary, by_pn)
        except Exception:                                            # noqa: BLE001
            got = None
        if not got:
            continue
        part["bevel_reading"] = got
        pn = str(part.get("part_number") or "this panel")
        qs = part.get("manufacturing_questions")
        if got["taken"]:
            if isinstance(qs, list):
                part["manufacturing_questions"] = [
                    q for q in qs if not (isinstance(q, dict) and q.get("subject") == FRAME_QUESTION)]
            _solid(part, got)
            part["bevelled_edges"] = {"angle_deg": got["angle_deg"], "run_mm": got["run_mm"],
                                      "edges": got["edges"],
                                      "length_mm": round(got["bevelled_edge_mm"], 1),
                                      "outline_perimeter_mm": round(got["outline_perimeter_mm"], 1),
                                      "evidence": got["because"], "sheet_of": got["sheet_of"]}
            pages = ", ".join(str(p) for p in got["pages"] if p)
            part.setdefault("review_flags", []).append(
                f"BEVEL, NOT A CUT-OUT: the lines inside {pn}'s outline sit "
                f"{got['inset_mm']:g} mm in from {got['edges']} edge(s) and {got['because']} "
                f"({got['sheet_of']}'s sheet, page {pages}). The panel is solid: area "
                f"{got['outline_area_mm2']:,.0f} mm2, cut path the outline. "
                f"{got['bevelled_edge_mm']:,.0f} mm of edge is bevelled at "
                f"{got['angle_deg']:g} degrees: machining the CNC row must cover. The CNC row "
                f"times it as a second pass over that length with a bevel-tool set-up, both "
                f"house allowances (LABOUR_RULES cnc_routing): confirm them."
                + (f" The inner lines' layer ({', '.join(got['layer_support'])}) agrees."
                   if got["layer_support"] else "")
                + f" Not checked: {MODEL_NOT_READ}.")
            taken.append(pn)
            continue
        # Not taken: the question stands, and says what else the inset reads as.
        if isinstance(qs, list):
            for q in qs:
                if isinstance(q, dict) and q.get("subject") == FRAME_QUESTION \
                        and "bevel" not in str(q.get("assumption") or "").lower():
                    q["assumption"] = (
                        f"{q.get('assumption')}. The lines inside sit {got['inset_mm']:g} mm "
                        f"in, which a bevel at about 45 degrees on {got['thickness_mm']:g} mm "
                        f"board also draws; nothing on {got['sheet_of'] or pn}'s sheet prints "
                        f"a bevel angle or word that agrees, so it is not taken")
                    q["action"] = (f"{q.get('action')}; for a bevel, give its angle and the "
                                   f"edges it is on")
    return taken
