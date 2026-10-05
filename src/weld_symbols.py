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
    fillet  a triangle standing on the line — a closed curve, or (ISO callouts with the
            dashed identification line) a vertical leg and a slant drawn as strokes

A circle at the reference line's END is not a spot: it is the weld-all-round modifier at the
arrow junction, recorded as `all_round` and never counted as a weld type.

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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

# In PDF points (1 pt = 0.353 mm).
_H_TOL = 0.35                 # a horizontal line's rise
_REF_LEN = (6.0, 80.0)        # a reference line's length
_LEADER_REACH = 1.2           # how far a leader's end may sit from the reference line's end
_CIRCLE_D = (1.8, 9.0)        # a weld-symbol circle's diameter
_ON_LINE = 0.9                # a symbol centre's distance from the reference line
_ID_GAP = (0.8, 6.0)          # the ISO dashed identification line's offset from the reference


def _dashed(ln: Mapping[str, Any]) -> bool:
    """A stroke with a dash pattern that has marks in it.

    A SOLID STROKE IS WRITTEN TWO WAYS, AND THE READER KNEW ONE OF THEM. pdfplumber gives a
    solid line as dash None — the 12527-22 riser's sheets — or as ([], 0), an explicit `[] 0 d`
    in the content stream — every sheet of the 12173-03 pack (3,465 of the 4,153 lines on the
    frame weld assembly's page 6). ([], 0) is truthy, so every solid line on that pack read
    as dashed, no reference line was ever found, and the reader returned nothing for sheets
    that draw fillet callouts on 201, 202, 203, 04M and 05M. Only a pattern with marks is
    dashed."""
    d = ln.get("dash")
    if not d:
        return False
    pat = d[0] if isinstance(d, (list, tuple)) and d and isinstance(d[0], (list, tuple)) else d
    return bool(pat)


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
    solid = [ln for ln in lines if _is_horizontal(ln) and not _dashed(ln)
             and _REF_LEN[0] <= _length(ln) <= _REF_LEN[1]]
    slanted = [ln for ln in lines if not _is_horizontal(ln)]
    dashed = [ln for ln in lines if _is_horizontal(ln) and _dashed(ln)]
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
        out.append({"x0": x0, "x1": x1, "y": y, "identification_line": ident is not None,
                    # THE SYMBOL MAY SIT ON THE DASHED LINE (D-392). ISO 2553 puts the symbol
                    # on the identification line for an other-side weld; 12696-01-101 draws
                    # both its fillets there, and a reader that looked only on the reference
                    # line called them "unclassified", so the weld reached the book as an
                    # inference to be asked about instead of a drawn weld.
                    "ident_y": float(ident["top"]) if ident is not None else None})
    return out


def _fillet_from_strokes(lines: Sequence[Mapping[str, Any]], y: float, x0: float,
                         x1: float) -> Optional[float]:
    """The x of a fillet triangle drawn as STROKES on the reference line at y, else None.

    12173-03 p.6 draws 201's fillet as three separate lines, not one closed curve: a vertical
    leg (433.7, 145.39)-(433.7, 150.69) standing on the reference line, a slant from its free
    end back down to the line, and the base, which IS the reference line. The closed-curve
    test never saw it. A leg of symbol height standing on the line, inside its x-range, with a
    slant from the leg's free end that lands back on the line inside its x-range, is the
    triangle."""
    for v in lines:
        if _is_horizontal(v) or _dashed(v) or abs(float(v["x1"]) - float(v["x0"])) > 0.3:
            continue
        top, bot, vx = float(v["top"]), float(v["bottom"]), float(v["x0"])
        if not (_CIRCLE_D[0] <= bot - top <= _CIRCLE_D[1]) or not (x0 - 0.5 <= vx <= x1 + 0.5):
            continue
        if abs(bot - y) <= _ON_LINE:
            apex = top
        elif abs(top - y) <= _ON_LINE:
            apex = bot
        else:
            continue
        for s in lines:
            if s is v or _is_horizontal(s) or abs(float(s["x1"]) - float(s["x0"])) <= 0.3:
                continue
            e = _ends(s)
            if any(abs(ex - vx) <= 0.6 and abs(ey - apex) <= 0.6 for ex, ey in e) and \
                    any(abs(ey - y) <= _ON_LINE and x0 - 0.5 <= ex <= x1 + 0.5 for ex, ey in e):
                return vx
    return None


def read_weld_symbols(lines: Sequence[Mapping[str, Any]],
                      curves: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per weld callout on the sheet: {kind, x, y, identification_line, all_round}."""
    found: List[Dict[str, Any]] = []
    circles = [c for c in (_circle(cv) for cv in curves) if c is not None]
    horizontal = [ln for ln in lines if _is_horizontal(ln)]
    for ref in reference_lines(lines):
        y, x0, x1 = ref["y"], ref["x0"], ref["x1"]
        # The lines a symbol may stand on: the reference line, and the identification line
        # where the callout has one (an other-side weld, D-392).
        _on = [y] + ([ref["ident_y"]] if ref.get("ident_y") is not None else [])
        kind = None
        at = None
        all_round = False
        for cx, cy, d in circles:
            if min(abs(cy - ly) for ly in _on) > _ON_LINE:
                continue
            # THE CIRCLE AT THE ARROW JUNCTION IS "WELD ALL ROUND", NOT A SPOT. 12173-03 p.9
            # draws the tube frame's fillet all round: the circle sits on the reference line's
            # end (centre x 543.75 against a line end at 543.8). Read as a spot it made 04M
            # and 05M "spot welded only" and ruled their arc weld and dressing out. Either
            # end, because reference_lines can take the tail fork for the leader.
            if min(abs(cx - x0), abs(cx - x1)) <= _LEADER_REACH:
                all_round = True
                continue
            # A SPOT OR SEAM SITS ON THE LINE, so the range stays the line's own. Widening it
            # past the ends turns a hole or a balloon in line with the reference into a spot,
            # and a spot-only reading rules out an arc weld — money removed on a false read.
            if not (x0 - 0.5 <= cx <= x1 + 0.5):
                continue
            # A seam weld is the same circle with two parallel lines through it.
            crossing = [h for h in horizontal
                        if min(abs(float(h["top"]) - ly) for ly in _on) > _ON_LINE
                        and abs(float(h["top"]) - cy) <= d / 2.0
                        and float(h["x0"]) <= cx <= float(h["x1"])
                        and _length(h) <= 3.0 * d]
            kind, at = ("seam" if len(crossing) >= 2 else "spot"), cx
            break
        if kind is None:
            for cv in curves:
                for ly in _on:
                    tri = _triangle_on(cv, ly)
                    if tri and x0 - 0.5 <= tri[0] <= x1 + 0.5:
                        kind, at = "fillet", tri[0]
                        break
                if kind:
                    break
        # Strokes are accepted only on an ISO callout (the dashed identification line): two
        # loose lines meeting a reference line are too common on a sheet to name a weld alone.
        if kind is None and ref["identification_line"]:
            for ly in _on:
                fx = _fillet_from_strokes(lines, ly, x0, x1)
                if fx is not None:
                    kind, at = "fillet", fx
                    break
        if kind is None and not ref["identification_line"]:
            continue                 # a line meeting a line is not a callout without a symbol
        found.append({"kind": kind or "unclassified", "x": round(at if at is not None
                                                                 else (x0 + x1) / 2.0, 1),
                      "y": round(y, 1), "identification_line": ref["identification_line"],
                      "all_round": all_round})
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


def _symbol_ops() -> Dict[str, str]:
    """What a named symbol on a part's own sheet states (config.WELD_SYMBOL_OPERATION)."""
    try:
        import config
        return dict(getattr(config, "WELD_SYMBOL_OPERATION", None) or {"fillet": "welding"})
    except Exception:                                                # noqa: BLE001
        return {"fillet": "welding"}


def arc_weld_symbols(counts: Optional[Mapping[str, Any]]) -> int:
    """How many callouts on the sheet name an ARC weld. A seam is ISO resistance seam welding
    and an unclassified callout names nothing, so neither counts (D-382 counted seams)."""
    return sum(int((counts or {}).get(k) or 0) for k, op in _symbol_ops().items()
               if op == "welding")


def describe_weld_symbols(counts: Optional[Mapping[str, Any]], pages: Sequence[Any] = ()) -> str:
    """THE sentence for what the symbol reader found on a part's own sheet.

    It reports a READING — "found" or "named no" — never that a sheet "carries" no symbol. The
    reader is blind to some drawings (a spot circle drawn tangent above the line, an AWS
    stroke fillet with no identification line, butt and plug symbols), so absence of a reading
    is not absence of a weld. An unclassified callout is never called a weld symbol. None means
    the sheet was not read at all."""
    if counts is None:
        return "its own sheet was not read for weld symbols"
    pg = [str(p) for p in (pages or []) if p not in (None, "")]
    where = f"its own sheet (p.{', '.join(pg)})" if pg else "its own sheet"
    named = {str(k): int(v) for k, v in counts.items()
             if str(k) != "unclassified" and isinstance(v, (int, float)) and v}
    if not named:
        return f"the weld-symbol reader named no weld symbol on {where}"
    return ("the weld-symbol reader found "
            + ", ".join(f"{v} {k}" for k, v in sorted(named.items()))
            + f" weld symbol(s) on {where}")


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
                                                          "text": "", "finish": "",
                                                          "finishes": []})
                    for k, v in read_page(page).items():
                        slot["counts"][k] = slot["counts"].get(k, 0) + v
                    slot["pages"].append(i)
                    slot["text"] += _clean_pn(text)
                    try:
                        _fin = str((_title_block_fields(page) or {}).get("finish") or "")
                    except Exception:                                # noqa: BLE001
                        _fin = ""
                    # ONE PAGE'S FINISH DOES NOT SPEAK FOR A SLOT OF SEVERAL SHEETS. Each page's
                    # finish is kept; the slot's finish is the one they agree on, else none.
                    # 12173-07-2's three member sheets (RAW) were pooled under the GA's key and
                    # took page 1's POWDER COATED.
                    if _fin:
                        slot["finishes"].append(_fin.upper())
                        slot["finish"] = (slot["finishes"][0]
                                          if len(set(slot["finishes"])) == 1 else "")
        except Exception:                                            # noqa: BLE001
            continue
    return out


def _says_welded(finish: Any) -> bool:
    """A title block whose FINISH field states the part leaves the bench (arc) welded.

    ONE VOCABULARY. The statement words are config's (FINISH_FIELD_PROCESS_STATEMENTS), read
    through finish_rules.process_statements — the same reader the finish census uses — so
    this reader and the check that asks whether the statement is charged cannot disagree
    about what "WELDED" means. A spot-weld statement is discharged by the Spotweld row, not
    by arc welding, so it does not stamp `welding` here."""
    try:
        from finish_rules import process_statements
    except Exception:                                                # noqa: BLE001
        return bool(re.search(r"\bWELDED\b", str(finish or "").upper()))
    return any("welding" in ops for ops in process_statements(finish)[0].values())


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

    Returns {"stated": [...], "questioned": [...], "joined_by_symbol": [...]}."""
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
        # WHICH STATEMENT IT WAS. The route compiler tells a weld the sheet DRAWS (a symbol,
        # the member's own) from one its FINISH field states (how the part leaves the shop):
        # the latter, on a member of a welded assembly with no symbol of its own, is the
        # assembly's joint seen from the member (D-387).
        part["weld_stated_by_finish"] = True
        part.setdefault("review_flags", []).append(
            f"WELDED per its own sheet: the title block's FINISH reads "
            f"'{by_part[pn].get('finish')}' — a stated weld, not an inference")
        stated.append(str(part.get("part_number") or pn))
    joined: List[str] = []
    for pn, facts in by_part.items():
        finish = str(facts.get("finish") or "")
        if not finish or _says_welded(finish):
            continue
        part = by_pn.get(pn)
        if part is None or "welding" in (part.get("operations_ruled_out") or {}):
            continue                      # spot welded per its own symbols: already settled
        text = str(facts.get("text") or "")
        members = sorted(m for m in welded if m != pn and m in text)
        if not members:
            continue
        _names = ", ".join(str((by_pn.get(m) or {}).get("part_number") or m) for m in members)
        counts = facts.get("counts") if isinstance(facts.get("counts"), Mapping) else None
        pages = list(facts.get("pages") or [])
        # WHAT THE READER FOUND, NEVER WHAT THE SHEET "SHOWS". Until the stroke-fillet and
        # solid-dash fixes the reader returned nothing for 201's own sheet, which draws two
        # ISO fillet callouts at the 202/203 joint; "shows no arc-weld symbol" was false there.
        _drawn = describe_weld_symbols(counts, pages)
        if arc_weld_symbols(counts):
            # Stated by apply_to_parts from the symbols; say why the members do not double it.
            part.setdefault("review_flags", []).append(
                f"welded on assembly: {_drawn} — the joint between {_names}, whose own sheets "
                f"state FINISH: WELDED for their own welds")
            joined.append(str(part.get("part_number") or pn))
            continue
        _q = {
            "issue": (f"Is {part.get('part_number')} welded itself? Its members {_names} each "
                      f"state FINISH: WELDED on their own sheets; its own sheet states FINISH "
                      f"'{finish}' and {_drawn}, which says how it is finished and not how "
                      f"its members are joined"),
            "assumption": ("whatever the route charges for welding and dressing on it stands "
                           "until answered — nothing is removed on this evidence"),
            "action": ("read the joint between the members on its sheet: if they are bolted, "
                       "slotted or only welded within themselves, rule the weld and dressing "
                       "off this assembly; if they are welded to each other, confirm it"),
            "source": "weld_symbols.apply_finish_welds",
            # ASKED ONLY WHERE MONEY RIDES ON IT. An uncharged weld cannot be double-charged,
            # so costed_facts raises this as a decision only when the sheet charges one of
            # these on the part, with those rows' money; otherwise the flag below stands alone.
            "subject": "welding",
            "charged_operations": ["welding", "spot_welding", "dress_welds"],
            # The operations it asks about, as fields: a consistency check's ruling on the
            # same assembly and operation is this question, netted onto it (costed_facts).
            "operations": ["welding", "dress_welds"],
        }
        qs = part.setdefault("manufacturing_questions", [])
        if isinstance(qs, list) and not any(isinstance(x, dict) and x.get("issue") == _q["issue"]
                                            for x in qs):
            qs.append(_q)
            part.setdefault("review_flags", []).append(
                f"WELD ON THIS ASSEMBLY NOT SETTLED: {_names} state FINISH: WELDED; this sheet "
                f"states FINISH '{finish}' and {_drawn}. Any weld the route charges here stands "
                f"and is asked; none is added or removed")
        questioned.append(str(part.get("part_number") or pn))
    return {"stated": stated, "questioned": questioned, "joined_by_symbol": joined}


# The coat a title block's FINISH names, and the operation that applies it.
_COAT_OP_BY_FAMILY = {"powder": "powder_coating", "wet_spray": "wet_spray"}


def _coatable_member(member: Mapping[str, Any], member_finish: str, op: str,
                     coated_assemblies: Set[str]) -> Tuple[bool, str]:
    """Is this direct member something the assembly's coat would be applied to? (ok, why not).

    Read from the member's own record and its own sheet's FINISH (D-387): a bought item
    arrives finished unless its sheet states RAW; nothing non-metal goes through the powder
    oven (a board can be wet sprayed); a sub-assembly whose own sheet names a coat is coated
    there (this reader stamps it). A LEAF that repeats the product's finish on its own sheet is
    still something to coat — whether it is coated on its own line or as the assembly is the
    route compiler's dedup question, not this reader's. RAW, a pointer to the assembly, or
    silence all mean "coated as the assembly"."""
    try:
        from finish_rules import finish_families, stated_finish
        from stock_form_rules import non_metal_reason
        from bought_in_policy import is_bought_in
    except Exception:                                            # noqa: BLE001
        return True, ""
    fin = str(member_finish or "").strip().upper() or (
        "" if member.get("finish_inherited_from") else stated_finish(member))
    fams = finish_families(fin) if fin else set()
    raw_stated = "bare" in fams
    if is_bought_in(dict(member)) and not raw_stated:
        return False, "bought in"
    if op == "powder_coating":
        why = non_metal_reason(str(member.get("normalized_material") or member.get("material") or ""))
        if why:
            return False, f"{why}, not metal"
    if _clean_pn(member.get("part_number")) in coated_assemblies:
        return False, "a sub-assembly coated on its own sheet"
    return True, ""


def apply_finish_coats(parts: Sequence[Dict[str, Any]],
                       by_part: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """An ASSEMBLY whose own title block states a coat is coated — where it holds something to
    coat (D-385, D-387).

    12173-07-2-GA (the trough) and 12173-07-GA (the rack) each print FINISH: POWDER COATED on
    their own sheet over members stated RAW; neither carried a coat on the 2 Oct 03:17 book,
    because an assembly minted from the parts list has no page text of its own for the
    note readers, and its members' RAW correctly ruled theirs out. The sheet's own FINISH
    field is read here for the assembly exactly as D-378 reads WELDED: the coat joins its
    operations as a drawing reading, and its stated finish is recorded so every coat gate
    reads the same words. Leaves are left to the readers that already handle them; a part
    whose coat is ruled out keeps the ruling.

    D-385 stamped every assembly whose sheet named a coat, and the next book coated the
    product's top GA (members: boards, a frame coated on its own sheet, fixings) over
    3.111 m² of MDF and MFC, and the rack's parent GA beside the two sub-GAs that each state
    their own coat. The title block states the product's finish; the booth object is the raw
    metal the assembly holds. So the coat is stamped only where a direct member is something
    to coat (_coatable_member); where every member is bought in, non-metal, coated on its own
    sheet or a coated sub-assembly, the coat is ruled out on this record with the members
    named — the one ruling the estimator and the route both honour. An assembly whose members
    cannot be seen here is stamped; the route compiler's gate reads the finished graph.
    Returns the part numbers stated."""
    try:
        from finish_rules import finish_families
        import source_precedence as _sp
    except Exception:                                            # noqa: BLE001
        return []
    stated: List[str] = []
    by_pn = {_clean_pn(p.get("part_number")): p for p in parts or () if isinstance(p, dict)}
    # Sub-assemblies whose own sheet names a coat: coated there, not again on their parent.
    coated_assemblies: Set[str] = set()
    for pn, facts in by_part.items():
        part = by_pn.get(pn)
        if part is None or not (part.get("is_assembly_parent") or part.get("is_sub_assembly")
                                or part.get("assembly_children")):
            continue
        if any(f in _COAT_OP_BY_FAMILY for f in finish_families(str(facts.get("finish") or ""))):
            coated_assemblies.add(pn)
    members_of: Dict[str, List[str]] = {}
    for p in parts or ():
        if isinstance(p, dict) and p.get("owning_assembly"):
            members_of.setdefault(_clean_pn(p["owning_assembly"]), []).append(
                _clean_pn(p.get("part_number")))
    for pn, facts in by_part.items():
        finish = str(facts.get("finish") or "").strip()
        part = by_pn.get(pn)
        if not finish or part is None:
            continue
        if not (part.get("is_assembly_parent") or part.get("is_sub_assembly")
                or part.get("assembly_children")):
            continue
        fams = finish_families(finish)
        ops_wanted = [_COAT_OP_BY_FAMILY[f] for f in sorted(fams) if f in _COAT_OP_BY_FAMILY]
        if not ops_wanted:
            continue
        ops = part.setdefault("textual_operations", [])
        if not isinstance(ops, list):
            continue
        if not str(part.get("normalized_finish") or "").strip():
            _sp.apply_field(part, "normalized_finish", finish.upper(), "drawing_deterministic")
        member_pns: List[str] = []
        for _k in list(part.get("assembly_children") or []) + members_of.get(pn, []):
            _ck = _clean_pn(_k)
            if _ck and _ck != pn and _ck not in member_pns and _ck in by_pn:
                member_pns.append(_ck)
        ruled = part.setdefault("operations_ruled_out", {}) if member_pns else (
            part.get("operations_ruled_out") or {})
        added: List[str] = []
        for op in ops_wanted:
            if op in ruled:
                continue
            classes: List[str] = []
            something = not member_pns          # unseen members: stamp, the route gate reads
            for _m in member_pns:
                _ok, _why = _coatable_member(by_pn[_m], str((by_part.get(_m) or {}).get("finish")
                                                            or ""), op, coated_assemblies)
                if _ok:
                    something = True
                    break
                classes.append(f"{by_pn[_m].get('part_number') or _m} ({_why})")
            if not something:
                _why_not = (f"nothing on {part.get('part_number') or pn} to coat: its title "
                            f"block's FINISH reads '{finish}', but its members are "
                            f"{'; '.join(classes)} — the finish is carried on their own lines")
                ruled[op] = _why_not
                for _f in ("textual_operations", "inferred_operations", "operations"):
                    if isinstance(part.get(_f), list):
                        part[_f] = [o for o in part[_f] if str(o) != op]
                part.setdefault("review_flags", []).append(
                    f"{op} NOT charged on this assembly: {_why_not}")
                continue
            _srcs = part.setdefault("operation_sources", {})
            if op in ops or op in (part.get("inferred_operations") or []):
                # ALREADY THERE FROM A WEAKER READER (D-392). 12696-01-101's powder had been
                # inferred from the page before this reader ran, so the sheet's own FINISH was
                # never recorded and the book carried the coat at rank 20, "inference", while
                # its words cited the title block. The statement is the stronger source.
                if _sp.rank(_srcs.get(op)) < _sp.rank("drawing_deterministic"):
                    _srcs[op] = "drawing_deterministic"
                    if op not in ops:
                        ops.append(op)
                    added.append(op)
                continue
            ops.append(op)
            _srcs.setdefault(op, "drawing_deterministic")
            added.append(op)
        if added:
            part.setdefault("review_flags", []).append(
                f"{'/'.join(added)} per its own sheet: the title block's FINISH reads "
                f"'{finish}' — the coat is this assembly's, whatever its members state")
            stated.append(str(part.get("part_number") or pn))
    return stated


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
        part["weld_symbol_pages"] = list(hit.get("pages") or [])
        # AN ARC-WELD SYMBOL ON A PART'S OWN SHEET STATES THE WELD. 12173-03-04M and 05M draw a
        # fillet all round on their tube corners; 202 and 203 a fillet for their tabs; 201 two
        # fillets at the 202/203 joint. All were "inferred, not drawn" — or not welded at all —
        # because nothing turned a symbol into a statement. A fillet (config
        # WELD_SYMBOL_OPERATION) is a reading of the drawing; a seam or an unnamed callout
        # states nothing.
        if arc_weld_symbols(counts) and "welding" not in (part.get("operations_ruled_out") or {}):
            _ops = part.setdefault("textual_operations", [])
            if isinstance(_ops, list) and "welding" not in _ops:
                _ops.append("welding")
            part.setdefault("operation_sources", {})["welding"] = "drawing_deterministic"
            _flag = (f"WELDED per the drawing: "
                     f"{describe_weld_symbols(counts, part['weld_symbol_pages'])}")
            if _flag not in (part.get("review_flags") or []):
                part.setdefault("review_flags", []).append(_flag)
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
        if arc_weld_symbols(mine):
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
