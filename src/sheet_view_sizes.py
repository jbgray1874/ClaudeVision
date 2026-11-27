"""A part drawn as one view of a sheet that draws several takes its size from its own view
(Hotel Chocolat, 1050mm plinth, 26 Nov 2026).

A.34494's parts list names drawing B.34495 three times: TOP PANEL x1, SIDE PANEL x4, BASE
PANEL x1. B.34495 draws all three. Its DXF is the drawing sheet, not a flat pattern, so it
gives no blank; but each view carries the panel's label (a SolidWorks "Part Information
Block": its description and material) and the dimensions printed around it:

    SIDE PANEL  1050 x 300 x 18      TOP PANEL  300 x 300 x 18      BASE PANEL  281 x 281 x 18

The three lines were one part "B.34495" at 400 x 300 x6 on the pilot book. Each member of the
drawing (bom_pipeline.number_drawing_members, "B34495-1") now takes the length and width
printed on the view whose label is its own description.

How a figure is put with a view, and when nothing is put:
  * a dimension's figure is the text it prints, never its measured length (a sheet is drawn
    to scale: 466.7 on the sheet is the 1050 it prints);
  * dimensions are grouped into views by where their measured points sit: points closer than
    a small share of the sheet are one view;
  * a label belongs to the view directly above it (where SolidWorks places it), and a view
    holds one label or none of them do;
  * the length is the largest figure along one axis and the width the largest along the
    other, the gauge (the label's "18mm THICK", which the view also prints) excluded; a view
    with figures on one axis only gives no size.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SOURCE = "drawing_view_dimensions"
_LABEL_BLOCK = "Part Information Block"
_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")
_GAUGE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*THICK", re.IGNORECASE)


def _key(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _printed(dim) -> Optional[float]:
    """The figure a dimension prints, read from its own geometry block."""
    try:
        blk = dim.get_geometry_block()
    except Exception:                                                # noqa: BLE001
        blk = None
    for e in (blk or []):
        if e.dxftype() == "MTEXT":
            text = e.plain_text()
        elif e.dxftype() == "TEXT":
            text = e.dxf.text
        else:
            continue
        m = _NUMBER.match(str(text).replace(",", "."))
        if m:
            return float(m.group(1))
    return None


def views_on_sheet(dxf_path: Any) -> List[Dict[str, Any]]:
    """[{label, material, gauge_mm, length_mm, width_mm}] for every labelled view the sheet's
    figures size; [] for a sheet with no labelled views or one this cannot read."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:                                                # noqa: BLE001
        return []
    msp = doc.modelspace()
    labels = []
    for ins in msp.query("INSERT"):
        if ins.dxf.name != _LABEL_BLOCK:
            continue
        texts = [str(a.dxf.text or "").strip() for a in ins.attribs]
        if not texts or not texts[0]:
            continue
        material = next((t.split(":", 1)[1].strip() for t in texts if t.upper().startswith("MATERIAL:")), "")
        gauge = _GAUGE.search(material)
        labels.append({"label": texts[0], "material": material,
                       "gauge_mm": float(gauge.group(1)) if gauge else None,
                       "at": (float(ins.dxf.insert.x), float(ins.dxf.insert.y))})
    if not labels:
        return []
    dims = []
    for d in msp.query("DIMENSION"):
        value = _printed(d)
        p2, p3 = d.dxf.get("defpoint2"), d.dxf.get("defpoint3")
        if value is None or p2 is None or p3 is None:
            continue
        dx, dy = abs(p3.x - p2.x), abs(p3.y - p2.y)
        axis = "h" if dx > 3 * dy else "v" if dy > 3 * dx else ""
        dims.append({"value": value, "axis": axis, "pts": [(p2.x, p2.y), (p3.x, p3.y)]})
    if not dims:
        return []
    xs = [x for d in dims for x, _ in d["pts"]]
    ys = [y for d in dims for _, y in d["pts"]]
    margin = 0.06 * max(max(xs) - min(xs), max(ys) - min(ys), 1.0)

    # Views: dimensions whose measured points come within the margin of each other.
    parent = list(range(len(dims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(dims)):
        for j in range(i + 1, len(dims)):
            if any(abs(a[0] - b[0]) <= margin and abs(a[1] - b[1]) <= margin
                   for a in dims[i]["pts"] for b in dims[j]["pts"]):
                parent[find(i)] = find(j)
    views: Dict[int, List[Dict[str, Any]]] = {}
    for i, d in enumerate(dims):
        views.setdefault(find(i), []).append(d)

    def box(members) -> Tuple[float, float, float, float]:
        px = [x for d in members for x, _ in d["pts"]]
        py = [y for d in members for _, y in d["pts"]]
        return min(px), max(px), min(py), max(py)

    # A label is the view directly above it.
    claimed: Dict[int, List[Dict[str, Any]]] = {}
    for lab in labels:
        x, y = lab["at"]
        above = [(box(v)[2] - y, k) for k, v in views.items()
                 if box(v)[0] - margin <= x <= box(v)[1] + margin and box(v)[2] >= y]
        if above:
            claimed.setdefault(min(above)[1], []).append(lab)
    out = []
    for k, labs in claimed.items():
        if len(labs) != 1:
            continue
        lab = labs[0]
        gauge = lab["gauge_mm"]
        figures = [d for d in views[k] if gauge is None or abs(d["value"] - gauge) > 1e-6]
        h = max((d["value"] for d in figures if d["axis"] == "h"), default=None)
        v = max((d["value"] for d in figures if d["axis"] == "v"), default=None)
        if not h or not v:
            continue
        out.append({"label": lab["label"], "material": lab["material"], "gauge_mm": gauge,
                    "length_mm": max(h, v), "width_mm": min(h, v)})
    return out


def _sheet_dxfs(summary: Any) -> List[Path]:
    """Every DXF the job was given, from the DXF merge's own report."""
    report = summary.get("dxf_augmentation") if isinstance(summary, dict) else None
    paths = []
    for entries in (report or {}).values():
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("path"):
                paths.append(Path(str(e["path"])))
    return sorted(set(paths), key=str)


def apply_sheet_view_sizes(parts: Sequence[Dict[str, Any]], summary: Any,
                           dxf_paths: Optional[Sequence[Any]] = None) -> List[str]:
    """Size each member of a drawing from its own labelled view. Returns the parts sized."""
    from drawing_reference import compact, reference_in_file_name
    import source_precedence as sp

    by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for path in (dxf_paths if dxf_paths is not None else _sheet_dxfs(summary)):
        ref = reference_in_file_name(Path(str(path)).stem)
        if ref and ref not in by_ref:
            views = views_on_sheet(path)
            if views:
                by_ref[ref] = views
    sized: List[str] = []
    for part in parts or ():
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "")
        m = re.match(r"^(.*)-(\d+)$", pn)
        ref = compact(part.get("drawing_member_of") or (m.group(1) if m else ""))
        views = by_ref.get(ref)
        if not views:
            continue
        mine = [v for v in views if _key(v["label"]) == _key(part.get("description"))]
        if len(mine) != 1:
            continue
        v = mine[0]
        had_material = bool(part.get("normalized_material"))
        _take_view_material(part, v)
        if not had_material and part.get("normalized_material"):
            part.setdefault("review_flags", []).append(
                f"{pn}: material and gauge from its own view's label on drawing {ref}: "
                f"{v['material']}")
            sized.append(pn)
        wrote = sp.apply_field(part, "blank_length_mm", v["length_mm"], SOURCE)
        wrote = sp.apply_field(part, "blank_width_mm", v["width_mm"], SOURCE) and wrote
        if not wrote:
            continue
        ng = part.setdefault("normalized_geometry", {})
        if isinstance(ng, dict):
            ng["blank_length_mm"], ng["blank_width_mm"] = v["length_mm"], v["width_mm"]
            ng["blank_length_mm_source"] = ng["blank_width_mm_source"] = SOURCE
        part["blank_from_drawing_view"] = dict(v, drawing=ref)
        part.setdefault("review_flags", []).append(
            f"{pn} sized {v['length_mm']:g} x {v['width_mm']:g} mm"
            + (f" x {v['gauge_mm']:g}" if v["gauge_mm"] else "")
            + f" from its own view on drawing {ref}, labelled '{v['label']}'"
            + (f" ({v['material']})" if v["material"] else "")
            + " — the figures printed on that view; the drawing is a sheet, not a flat pattern")
        if pn not in sized:
            sized.append(pn)
    return sized


def _take_view_material(part: Dict[str, Any], view: Dict[str, Any]) -> None:
    """A member's material and gauge are the ones on its own view's label (B.34495's panels:
    "MATERIAL:18mm THICK FR B MDF 3050 X 1220mm (30001651)"). Only where the part has none."""
    import source_precedence as sp
    from extractor_patterns import _extract_material_candidates, canonical_material

    found = _extract_material_candidates("MATERIAL: " + str(view.get("material") or ""))
    if found and not part.get("normalized_material"):
        sp.apply_field(part, "normalized_material", canonical_material(found[0]), "title_block")
        part.setdefault("material_text", view.get("material"))
        if view.get("gauge_mm") and not part.get("normalized_thickness_mm"):
            sp.apply_field(part, "normalized_thickness_mm", float(view["gauge_mm"]), "title_block")


# WHAT A SHEET SAYS ABOUT THE PART IT DRAWS, READ FROM ITS DXF (27 Nov 2026). A drawing exported
# as outlines has no text layer in its PDF; the same sheet's DXF carries the title block as
# text. A.34494's "FINISH: SPRAYED TO MATCH SEPIA BROWN RAL 8014 ..." was in its DXF alone, so
# the plinth tower was priced with no coat at all.
def sheet_text(dxf_path: Any) -> str:
    """Every word a drawing-sheet DXF prints: text, block text and block attributes."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:                                                # noqa: BLE001
        return ""
    out: List[str] = []

    def take(e, depth=0):
        kind = e.dxftype()
        if kind == "TEXT":
            out.append(str(e.dxf.text or ""))
        elif kind == "MTEXT":
            out.append(e.plain_text())
        elif kind == "INSERT" and depth < 3:
            out.extend(str(a.dxf.text or "") for a in e.attribs)
            name = str(e.dxf.name or "")
            blk = doc.blocks.get(name) if not name.startswith("*") else None
            for x in (blk or []):
                take(x, depth + 1)
    for e in doc.modelspace():
        take(e)
    return "\n".join(t for t in out if t)


def apply_sheet_title_facts(parts: Sequence[Dict[str, Any]], summary: Any,
                            dxf_paths: Optional[Sequence[Any]] = None) -> List[str]:
    """Give the part a drawing-sheet DXF draws the finish, material and gauge its title block
    prints, where the part has none. The sheet's part is the one its file name's drawing
    reference or its FINISHED PART NO. names, and exactly one. A gauge is taken only with a
    material from the same sheet: a sheet's standing notes print thicknesses too."""
    import source_precedence as sp
    from drawing_reference import compact, finished_parts_on_sheet, reference_in_file_name
    from extractor_patterns import extract_title_block_fields

    done: List[str] = []
    for path in (dxf_paths if dxf_paths is not None else _sheet_dxfs(summary)):
        ref = reference_in_file_name(Path(str(path)).stem)
        text = sheet_text(path)
        if not text:
            continue
        stock = finished_parts_on_sheet(text)
        mine = [p for p in parts or () if isinstance(p, dict) and (
            (ref and ref in (compact(p.get("part_number")), compact(p.get("drawing_reference"))))
            or (len(stock) == 1 and (str(p.get("part_number") or "") in stock
                                     or str(p.get("finished_part_no") or "") in stock)))]
        if len(mine) != 1:
            continue
        part = mine[0]
        fields = extract_title_block_fields(text)
        norm = fields.get("normalized") or {}
        wrote = []
        finish = norm.get("primary_finish")
        if finish and not part.get("normalized_finish"):
            if sp.apply_field(part, "normalized_finish", finish, "title_block"):
                part.setdefault("surface_finishes", [])
                if finish not in part["surface_finishes"]:
                    part["surface_finishes"].append(finish)
                wrote.append("finish")
                # THE COAT THE FINISH NAMES IS WORK ON THE PART: "SPRAYED TO MATCH ... RAL 8014"
                # is the spray booth, in the engine's own finish families (finish_rules).
                for op in _coat_operations(finish):
                    ops = part.setdefault("textual_operations", [])
                    if op not in ops:
                        ops.append(op)
                        wrote.append(op)
        material = norm.get("primary_material")
        if material and not part.get("normalized_material"):
            if sp.apply_field(part, "normalized_material", material, "title_block"):
                wrote.append("material")
                if norm.get("primary_thickness_mm") and not part.get("normalized_thickness_mm"):
                    sp.apply_field(part, "normalized_thickness_mm",
                                   float(norm["primary_thickness_mm"]), "title_block")
                    wrote.append("gauge")
        if wrote:
            pn = str(part.get("part_number") or "")
            part["sheet_title_facts"] = {"dxf": Path(str(path)).name, "finish": finish,
                                         "material": material, "took": wrote}
            part.setdefault("review_flags", []).append(
                f"{pn}: {', '.join(wrote)} read from its own drawing's DXF ({Path(str(path)).name})"
                f" — the PDF carries no text" + (f"; finish: {finish}" if finish else ""))
            done.append(pn)
    return done


def _coat_operations(finish: str) -> List[str]:
    """The coating operation(s) a stated finish names, through finish_rules' families; none
    for a finish no family recognises (an unread finish decides nothing)."""
    try:
        from finish_rules import _OPERATION_FAMILY, finish_families, states_only_a_process
    except Exception:                                                # noqa: BLE001
        return []
    if states_only_a_process(finish):
        return []
    fams = finish_families(finish)
    return [op for op, fam in _OPERATION_FAMILY.items()
            if fam in fams and op in ("powder_coating", "wet_spray", "plating", "anodising")]
