"""Weld symbols read off a drawing sheet's vectors (ISO 2553 / AWS A2.4).

12527-22-101, the TSE Footwear riser weldment, carries four weld callouts on its own sheet: a
leader arrow to the joint, a solid reference line, the dashed identification line ISO draws
beside it, and a small circle centred ON the reference line — the spot-weld symbol. There is
no text in any of them. The engine read none of it, inferred the weld from the word WELMENT,
charged Weld (CO2) and Dress Welds, and told the estimator there was "no weld note or symbol on
the drawing".

WHAT THIS READS. A weld callout is recognised only by its reference line: a horizontal solid
line with a leader meeting one end (a non-horizontal line with an end within reach). The ISO
dashed identification line beside it is recorded when present but not required, so an AWS
sheet reads too. Only a SYMBOL on the reference line classifies the weld:

    spot    a closed circle centred on the line
    seam    the same circle with two parallel lines through it
    fillet  a closed triangle standing on the line

Anything else on a reference line is `unclassified` and counted as such — a callout the reader
saw and could not name, which is a question for a person, not a weld type to guess.

WHAT IT DOES NOT DO. It does not read the number of spots or the pitch printed beside a symbol;
one callout is one weld location, and the caller says so. It does not look for callouts
anywhere but the sheet it is given. Tolerances are in PDF points and sized for symbols drawn
at the usual 2.5–5 mm; they are named here so a pack drawn at another scale is a one-line
change.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# In PDF points (1 pt = 0.353 mm).
_H_TOL = 0.35                 # a horizontal line's rise
_REF_LEN = (6.0, 80.0)        # a reference line's length
_LEADER_REACH = 1.2           # how far a leader's end may sit from the reference line's end
_CIRCLE_D = (1.8, 9.0)        # a weld-symbol circle's diameter
_ON_LINE = 0.9                # a symbol centre's distance from the reference line
_ID_GAP = (0.8, 6.0)          # the ISO dashed identification line's offset from the reference


def _is_horizontal(ln: Mapping[str, Any]) -> bool:
    return abs(float(ln.get("top", 0)) - float(ln.get("bottom", 0))) <= _H_TOL


def _length(ln: Mapping[str, Any]) -> float:
    return abs(float(ln.get("x1", 0)) - float(ln.get("x0", 0)))


def _ends(ln: Mapping[str, Any]) -> List[Tuple[float, float]]:
    pts = ln.get("pts")
    if pts and len(pts) >= 2:
        return [(float(pts[0][0]), float(pts[0][1])), (float(pts[-1][0]), float(pts[-1][1]))]
    return [(float(ln["x0"]), float(ln["top"])), (float(ln["x1"]), float(ln["bottom"]))]


def _closed(curve: Mapping[str, Any]) -> bool:
    pts = curve.get("pts") or []
    if len(pts) < 3:
        return False
    (ax, ay), (bx, by) = pts[0], pts[-1]
    return abs(ax - bx) < 0.3 and abs(ay - by) < 0.3


def _circle(curve: Mapping[str, Any]) -> Optional[Tuple[float, float, float]]:
    """(cx, cy, diameter) of a closed round curve, else None."""
    w = float(curve.get("x1", 0)) - float(curve.get("x0", 0))
    h = float(curve.get("bottom", 0)) - float(curve.get("top", 0))
    if not (_CIRCLE_D[0] <= w <= _CIRCLE_D[1]) or abs(w - h) > 0.25 * max(w, h):
        return None
    if len(curve.get("pts") or []) < 8 or not _closed(curve):
        return None
    return ((float(curve["x0"]) + float(curve["x1"])) / 2.0,
            (float(curve["top"]) + float(curve["bottom"])) / 2.0, w)


def _triangle_on(curve: Mapping[str, Any], y: float) -> Optional[Tuple[float, float]]:
    """(cx, height) of a closed 3-cornered curve with one edge lying on the line at y."""
    pts = [(float(a), float(b)) for a, b in (curve.get("pts") or [])]
    if not _closed(curve):
        return None
    corners = pts[:-1]
    if len(corners) != 3:
        return None
    on = [p for p in corners if abs(p[1] - y) <= _ON_LINE]
    if len(on) != 2:
        return None
    off = [p for p in corners if p not in on][0]
    h = abs(off[1] - y)
    if not (_CIRCLE_D[0] <= h <= _CIRCLE_D[1]):
        return None
    return (sum(p[0] for p in corners) / 3.0, h)


def reference_lines(lines: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every horizontal solid line with a leader meeting one of its ends."""
    solid = [ln for ln in lines if _is_horizontal(ln) and not ln.get("dash")
             and _REF_LEN[0] <= _length(ln) <= _REF_LEN[1]]
    slanted = [ln for ln in lines if not _is_horizontal(ln)]
    dashed = [ln for ln in lines if _is_horizontal(ln) and ln.get("dash")]
    out: List[Dict[str, Any]] = []
    for ln in solid:
        x0, x1 = sorted((float(ln["x0"]), float(ln["x1"])))
        y = float(ln["top"])
        leader = None
        for s in slanted:
            for ex, ey in _ends(s):
                if abs(ey - y) <= _LEADER_REACH and min(abs(ex - x0), abs(ex - x1)) <= _LEADER_REACH:
                    leader = s
                    break
            if leader is not None:
                break
        if leader is None:
            continue
        ident = None
        for d in dashed:
            gap = abs(float(d["top"]) - y)
            dx0, dx1 = sorted((float(d["x0"]), float(d["x1"])))
            overlap = min(x1, dx1) - max(x0, dx0)
            if _ID_GAP[0] <= gap <= _ID_GAP[1] and overlap >= 0.6 * (x1 - x0):
                ident = d
                break
        out.append({"x0": x0, "x1": x1, "y": y, "identification_line": ident is not None})
    return out


def read_weld_symbols(lines: Sequence[Mapping[str, Any]],
                      curves: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per weld callout on the sheet: {kind, x, y, identification_line}."""
    found: List[Dict[str, Any]] = []
    circles = [c for c in (_circle(cv) for cv in curves) if c is not None]
    horizontal = [ln for ln in lines if _is_horizontal(ln)]
    for ref in reference_lines(lines):
        y, x0, x1 = ref["y"], ref["x0"], ref["x1"]
        kind = None
        at = None
        for cx, cy, d in circles:
            if abs(cy - y) <= _ON_LINE and x0 - 0.5 <= cx <= x1 + 0.5:
                # A seam weld is the same circle with two parallel lines through it.
                crossing = [h for h in horizontal
                            if abs(float(h["top"]) - y) > _ON_LINE
                            and abs(float(h["top"]) - cy) <= d / 2.0
                            and float(h["x0"]) <= cx <= float(h["x1"])
                            and _length(h) <= 3.0 * d]
                kind, at = ("seam" if len(crossing) >= 2 else "spot"), cx
                break
        if kind is None:
            for cv in curves:
                tri = _triangle_on(cv, y)
                if tri and x0 - 0.5 <= tri[0] <= x1 + 0.5:
                    kind, at = "fillet", tri[0]
                    break
        if kind is None and not ref["identification_line"]:
            continue                 # a line meeting a line is not a callout without a symbol
        found.append({"kind": kind or "unclassified", "x": round(at if at is not None
                                                                 else (x0 + x1) / 2.0, 1),
                      "y": round(y, 1), "identification_line": ref["identification_line"]})
    return found


def count_by_kind(symbols: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in symbols or ():
        k = str(s.get("kind") or "unclassified")
        out[k] = out.get(k, 0) + 1
    return out


def read_page(page: Any) -> Dict[str, int]:
    """Weld callouts on one pdfplumber page, counted by kind. {} when there are none."""
    try:
        return count_by_kind(read_weld_symbols(page.lines or [], page.curves or []))
    except Exception:                                                # noqa: BLE001
        return {}


def only_spot_welds(counts: Mapping[str, int]) -> int:
    """How many spot-weld callouts, when spot welds are the only weld the sheet NAMES; else 0.

    An unclassified callout does not count against it: across the packs on hand the reader
    sees dashed-paired leaders on sheets with no welding at all (a centre line beside a
    dimension), so an unnamed one is not evidence of an arc weld."""
    spots = int(counts.get("spot") or 0)
    others = sum(int(v or 0) for k, v in counts.items() if k not in ("spot", "unclassified"))
    return spots if spots and not others else 0


def _clean_pn(value: Any) -> str:
    return "".join(str(value or "").upper().split())


def sheet_weld_symbols(pdf_path: Any) -> Dict[str, Dict[str, Any]]:
    """{part number: {"counts": {...}, "pages": [n, ...]}} for every sheet whose title block
    names its part and whose vectors carry a weld callout."""
    try:
        import pdfplumber
        from drawing_facts import _title_block_part
    except Exception:                                                # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                counts = read_page(page)
                if not counts:
                    continue
                pn = _title_block_part(page, page.extract_text() or "")
                if not pn:
                    continue
                slot = out.setdefault(_clean_pn(pn), {"counts": {}, "pages": [], "text": ""})
                for k, v in counts.items():
                    slot["counts"][k] = slot["counts"].get(k, 0) + v
                slot["pages"].append(i)
                # The sheet's words, squashed, so its own parts list can say who its members
                # are when no hierarchy has been built yet.
                slot["text"] += _clean_pn(page.extract_text() or "")
    except Exception:                                                # noqa: BLE001
        return out
    return out


def sheet_weld_facts(pdf_paths: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Every sheet of every PDF in the pack, by the part its title block names:
    {"counts", "pages", "text", "finish"}. A multi-sheet pack (12173's 02-, 03-, 07-GA files)
    is read whole — the weld on 12173-03-202 is stated on the 03-GA PDF, not the product's."""
    try:
        import pdfplumber
        from drawing_facts import _title_block_part, _title_block_fields
    except Exception:                                                # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    seen = set()
    for pdf_path in pdf_paths or ():
        if not pdf_path or str(pdf_path).lower() in seen:
            continue
        seen.add(str(pdf_path).lower())
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    pn = _title_block_part(page, text)
                    if not pn:
                        continue
                    slot = out.setdefault(_clean_pn(pn), {"counts": {}, "pages": [],
                                                          "text": "", "finish": ""})
                    for k, v in read_page(page).items():
                        slot["counts"][k] = slot["counts"].get(k, 0) + v
                    slot["pages"].append(i)
                    slot["text"] += _clean_pn(text)
                    try:
                        _fin = str((_title_block_fields(page) or {}).get("finish") or "")
                    except Exception:                                # noqa: BLE001
                        _fin = ""
                    if _fin and not slot["finish"]:
                        slot["finish"] = _fin.upper()
        except Exception:                                            # noqa: BLE001
            continue
    return out


def _says_welded(finish: Any) -> bool:
    """A title block whose FINISH field states the part leaves the bench welded."""
    return bool(re.search(r"\bWELDED\b", str(finish or "").upper()))


def apply_finish_welds(parts: Sequence[Dict[str, Any]],
                       by_part: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[str]]:
    """What a sheet's FINISH field says about welding.

    12173-03: the FRONT and SIDE frames (202, 203) each state FINISH: WELDED on their own
    sheets, and the FRAME WELD ASSEMBLY that holds them (201) states FINISH: POWDER COATED.
    The book read none of it: all three were "inferred, not drawn".

      * A part whose own sheet says FINISH: WELDED is welded by the drawing, not by inference.
      * An assembly whose own sheet states ANOTHER finish, over members whose sheets say
        WELDED, is NOT settled by that. Its members' finish proves THEIR welds; it does not
        prove there is no further weld joining them (D-382 — D-378 ruled the parent's weld
        out on this and that was a conclusion the evidence does not carry). Where the
        parent's own sheet shows an arc-weld symbol the weld stands; otherwise whatever the
        route charges on it stands and a manufacturing decision is raised naming the
        evidence, for a person reading the joint on the drawing.

    Returns {"stated": [...], "questioned": [...]}."""
    stated: List[str] = []
    questioned: List[str] = []
    by_pn = {_clean_pn(p.get("part_number")): p for p in parts or () if isinstance(p, dict)}
    welded = {pn for pn, f in by_part.items() if _says_welded(f.get("finish"))}
    for pn in sorted(welded):
        part = by_pn.get(pn)
        if part is None or "welding" in (part.get("operations_ruled_out") or {}):
            continue
        ops = part.setdefault("textual_operations", [])
        if isinstance(ops, list) and "welding" not in ops:
            ops.append("welding")
        part.setdefault("operation_sources", {})["welding"] = "drawing_deterministic"
        part.setdefault("review_flags", []).append(
            f"WELDED per its own sheet: the title block's FINISH reads "
            f"'{by_part[pn].get('finish')}' — a stated weld, not an inference")
        stated.append(str(part.get("part_number") or pn))
    for pn, facts in by_part.items():
        finish = str(facts.get("finish") or "")
        if not finish or _says_welded(finish):
            continue
        part = by_pn.get(pn)
        if part is None:
            continue
        text = str(facts.get("text") or "")
        members = sorted(m for m in welded if m != pn and m in text)
        if not members:
            continue
        counts = dict(facts.get("counts") or {})
        _arc = sum(int(counts.get(k) or 0) for k in ("fillet", "seam"))
        _names = ", ".join(str((by_pn.get(m) or {}).get("part_number") or m) for m in members)
        if _arc:
            part.setdefault("review_flags", []).append(
                f"welded as well as its members: its own sheet shows {_arc} arc-weld "
                f"symbol(s), beside FINISH '{finish}' and members {_names} stated WELDED")
            continue
        _q = {
            "issue": (f"Is {part.get('part_number')} welded itself? Its members {_names} each "
                      f"state FINISH: WELDED on their own sheets; its own sheet states FINISH "
                      f"'{finish}' and shows no arc-weld symbol, which says how it is finished "
                      f"and not how its members are joined"),
            "assumption": ("whatever the route charges for welding and dressing on it stands "
                           "until answered — nothing is removed on this evidence"),
            "action": ("read the joint between the members on its sheet: if they are bolted, "
                       "slotted or only welded within themselves, rule the weld and dressing "
                       "off this assembly; if they are welded to each other, confirm it"),
            "source": "weld_symbols.apply_finish_welds",
        }
        qs = part.setdefault("manufacturing_questions", [])
        if isinstance(qs, list) and not any(isinstance(x, dict) and x.get("issue") == _q["issue"]
                                            for x in qs):
            qs.append(_q)
        questioned.append(str(part.get("part_number") or pn))
    return {"stated": stated, "questioned": questioned}


def apply_to_parts(parts: Sequence[Dict[str, Any]], by_part: Mapping[str, Mapping[str, Any]]
                   ) -> List[str]:
    """Stamp each part with the weld callouts on its OWN sheet. Where spot welds are the only
    weld that sheet names, the part is spot welded: `spot_welding` joins its operations as a
    reading of the drawing, and an arc weld any other reader inferred is ruled out, with the
    reason, through the one ruling every stage honours (operations_ruled_out). Returns the
    part numbers so ruled."""
    ruled: List[str] = []
    for part in parts or ():
        if not isinstance(part, dict):
            continue
        hit = by_part.get(_clean_pn(part.get("part_number")))
        if not hit:
            continue
        counts = dict(hit.get("counts") or {})
        sheets = ", ".join(str(p) for p in hit.get("pages") or [])
        part["weld_symbols"] = counts
        n = only_spot_welds(counts)
        if not n:
            continue
        ops = part.setdefault("textual_operations", [])
        if isinstance(ops, list):
            for gone in ("welding", "dress_welds"):
                while gone in ops:
                    ops.remove(gone)
            if "spot_welding" not in ops:
                ops.append("spot_welding")
        part.setdefault("operation_sources", {})["spot_welding"] = "drawing_deterministic"
        part["spot_weld_count"] = n
        _why = (f"its own sheet ({sheets}) carries {n} ISO spot-weld symbol(s) and no other "
                f"weld symbol — the joint is spot welded, not arc welded")
        part.setdefault("operations_ruled_out", {})["welding"] = _why
        part.setdefault("operation_ruling_sources", {})["welding"] = "drawing_deterministic"
        part.setdefault("review_flags", []).append(
            f"SPOT WELDED per the drawing: {_why}. Charged on the Spotweld row; spot welds "
            f"leave no bead, so no weld dressing. The sheet prints no spot count beside the "
            f"symbols, so each callout is read as one weld location. A general note such as "
            f"'ALL WELDS TO BE TIG UNLESS STATED' gives way to the symbols, which state it")
        ruled.append(str(part.get("part_number") or ""))
        _rule_members(parts, part, hit, n, sheets, by_part)
    return ruled


def _rule_members(parts: Sequence[Dict[str, Any]], weldment: Mapping[str, Any],
                  hit: Mapping[str, Any], n: int, sheets: str,
                  by_part: Mapping[str, Mapping[str, Any]]) -> None:
    """The weldment's symbols say how ITS MEMBERS are joined, so an arc weld a member picked
    up from a general note ("ALL WELDS TO BE TIG UNLESS STATED" reaches every record on the
    pack) is ruled out on the member too. 12527-22's live book charged Weld (CO2) and Dress
    Welds against 01M and 02M.

    Members are the parts the weldment's own sheet names — its parts list — or its recorded
    children; no hierarchy has been built when this runs. A member whose own sheet names an
    arc weld keeps it."""
    own = _clean_pn(weldment.get("part_number"))
    text = str(hit.get("text") or "")
    kids = {_clean_pn(k) for k in (weldment.get("assembly_children") or [])}
    for m in parts or ():
        if not isinstance(m, dict) or m is weldment:
            continue
        pn = _clean_pn(m.get("part_number"))
        if not pn or pn == own or (pn not in kids and pn not in text):
            continue
        mine = (by_part.get(pn) or {}).get("counts") or {}
        if any(int(mine.get(k) or 0) for k in ("fillet", "seam")):
            continue
        _why = (f"joined into {weldment.get('part_number')} by spot welds — that sheet "
                f"({sheets}) carries {n} ISO spot-weld symbol(s) and no arc-weld symbol")
        ro = m.setdefault("operations_ruled_out", {})
        rs = m.setdefault("operation_ruling_sources", {})
        for op in ("welding", "dress_welds"):
            ro[op] = _why
            rs[op] = "drawing_deterministic"
        m.setdefault("review_flags", []).append(
            f"no arc weld or dressing on this part: {_why}")
