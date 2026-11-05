"""Why a single made part is welded, and where (D-718).

A WELD THE ENGINE INFERRED STAYS CHARGED, AND SAYS WHICH JOINT IT IS.

12676-01-GA2's stand, 12676-01-04M, is one folded sheet. Its record carried welding and weld
dressing that no reader recorded a source for, and the route printed both as "an unrecorded
source". JG's ruling (5 Nov 2026): a reasoned manufacturing inference stays in the estimate,
priced, with the joint named, the reason given and the allowance stated. Being one part does
not rule welding out: a folded part can close on a seam or leave corners to join. "No printed
weld symbol" alone removes nothing, and relabelling the charge "inferred" explains nothing.

So this module answers, from the part's own folds, the question the route left blank:

  * a CLOSING SEAM, where the folds turn the sheet through a full turn and its two free
    edges meet along the fold line;
  * CORNER SEAMS, where a tray or box is folded up on four sides and adjacent flanges meet
    at four open corners;
  * otherwise a PROVISIONAL JOINT: the weld the engine inferred is carried as one joint at
    the shop's allowance, said plainly, with the review question beside the charge.

It decides nothing about money. The weld stays on the route and is timed where it always was;
this is the manufacturing reason the route and the book print beside that time.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# Sources that say where an operation came from without saying why the work exists.
_NO_REASON_SOURCES = frozenset({"", "unrecorded", "unknown", "inference"})

# Words that name a part folded up on four sides: a tray, a box, a pan.
_FOUR_SIDED_WORDS = ("TRAY", "BOX", "PAN", "CASE", "HOOD", "COVER", "HOUSING", "ENCLOSURE",
                     "BIN", "CABINET", "DRAWER")

# How far the folds' total may sit from a full turn and still close the section.
_FULL_TURN_TOLERANCE_DEG = 10.0


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _angles(part: Mapping[str, Any]) -> List[float]:
    mf = part.get("manufacturing_features") if isinstance(part.get("manufacturing_features"),
                                                          Mapping) else {}
    for raw in (part.get("angles_deg"), part.get("bend_angles_deg"), mf.get("angles_deg")):
        if isinstance(raw, (list, tuple)):
            vals = [a for a in (_num(x) for x in raw) if a is not None and 0 < abs(a) < 180]
            if vals:
                return [abs(a) for a in vals]
    return []


def bend_count(part: Mapping[str, Any]) -> int:
    """The most folds any reading of this part counted, or 0."""
    mf = part.get("manufacturing_features") if isinstance(part.get("manufacturing_features"),
                                                          Mapping) else {}
    counts = [_num(part.get("bend_count_dxf")), _num(part.get("bend_count")),
              _num(mf.get("bend_count")), _num(part.get("fold_count_textual")),
              float(len(_angles(part)))]
    for key in ("solidworks_bend_features", "drawing_bend_callouts"):
        raw = part.get(key)
        if isinstance(raw, (list, tuple)):
            counts.append(float(len(raw)))
        elif _num(raw) is not None:
            counts.append(_num(raw))
    return int(max([c for c in counts if c is not None] or [0]))


def _fold_line_mm(part: Mapping[str, Any]) -> Optional[float]:
    """How long a fold line is: the blank side the folded part keeps whole, or the shorter
    blank side when the envelope does not say."""
    bl, bw = _num(part.get("blank_length_mm")), _num(part.get("blank_width_mm"))
    blank = [d for d in (bl, bw) if d]
    if not blank:
        return None
    env = part.get("product_envelope_mm") if isinstance(part.get("product_envelope_mm"),
                                                        Mapping) else {}
    dims = [d for d in (_num(env.get("length")), _num(env.get("width")), _num(env.get("height")),
                        _num(part.get("overall_length_mm")), _num(part.get("overall_width_mm")),
                        _num(part.get("overall_height_mm"))) if d]
    for b in sorted(blank):
        if any(abs(b - d) <= 2.0 for d in dims):
            return b
    return min(blank)


def weld_has_its_own_reason(part: Mapping[str, Any]) -> bool:
    """Does something already say why this part is welded: the drawing's words, a counted
    weld symbol, a stated weld length or joint count, a finish or brief that states it, or a
    reader that recorded where the weld came from?"""
    ev = part.get("operation_evidence") if isinstance(part.get("operation_evidence"),
                                                      Mapping) else {}
    if str(ev.get("welding") or "").strip():
        return True
    src = part.get("operation_sources") if isinstance(part.get("operation_sources"),
                                                      Mapping) else {}
    if str(src.get("welding") or "").strip().lower() not in _NO_REASON_SOURCES:
        return True
    ws = part.get("weld_symbols")
    if isinstance(ws, Mapping) and any((_num(v) or 0) > 0 for v in ws.values()):
        return True
    mf = part.get("manufacturing_features") if isinstance(part.get("manufacturing_features"),
                                                          Mapping) else {}
    if any((_num(x) or 0) > 0 for x in (part.get("weld_length_mm"), mf.get("weld_length_mm"),
                                        part.get("weld_joint_count"),
                                        mf.get("weld_joint_count"))):
        return True
    return bool(part.get("weld_stated_by_finish") or part.get("weld_stated_by_brief"))


def weld_joint_basis(part: Mapping[str, Any]) -> Dict[str, Any]:
    """The joint this one-piece part is welded at, why, and what is assumed.

    {"kind": "closing_seam" | "corner_seams" | "provisional", "joints": int,
     "seam_mm": float | None, "joint": str, "why": str, "assumption": str,
     "statement": str}"""
    pn = str(part.get("part_number") or "this part")
    folds = bend_count(part)
    angles = _angles(part)
    line = _fold_line_mm(part)
    desc = " ".join(str(part.get(k) or "") for k in ("description", "title")).upper()

    turn = sum(angles)
    if len(angles) >= 3 and abs(turn - 360.0) <= _FULL_TURN_TOLERANCE_DEG:
        joint = ("the closing seam where the folded ends meet"
                 + (f", along the {line:g} mm fold line" if line else ""))
        why = (f"its {len(angles)} folds ({' + '.join(f'{a:g}' for a in angles)} = "
               f"{turn:g} degrees) turn the sheet through a full turn, so its two free edges "
               f"meet and are welded to close the section")
        out = {"kind": "closing_seam", "joints": 1, "seam_mm": line, "joint": joint, "why": why,
               "assumption": "one closing seam, welded full length and dressed"}
    elif folds >= 4 and any(w in desc for w in _FOUR_SIDED_WORDS):
        env = part.get("product_envelope_mm") if isinstance(part.get("product_envelope_mm"),
                                                            Mapping) else {}
        dims = [d for d in (_num(env.get("length")), _num(env.get("width")),
                            _num(env.get("height"))) if d]
        height = min(dims) if len(dims) == 3 else None
        joint = ("the four corner seams where adjacent flanges meet"
                 + (f", each about {height:g} mm" if height else ""))
        why = (f"it is folded up on four sides ({folds} folds), which leaves the four corners "
               f"open; they are welded to close and square them")
        out = {"kind": "corner_seams", "joints": 4,
               "seam_mm": round(4 * height, 1) if height else None,
               "joint": joint, "why": why,
               "assumption": "four corner seams, welded and dressed"}
    else:
        _src = str(((part.get("operation_sources") or {}) if isinstance(
            part.get("operation_sources"), Mapping) else {}).get("welding") or "").strip()
        joint = "one joint, not located on the folds read"
        why = (f"the engine carries the weld it inferred for {pn}"
               + (f" ({_src})" if _src and _src.lower() not in ("unrecorded", "unknown") else "")
               + (f"; its {folds} fold(s) close no section and form no four-sided corner, so "
                  f"the joint is not located" if folds else
                  "; no fold geometry was read to locate the joint"))
        out = {"kind": "provisional", "joints": 1, "seam_mm": None, "joint": joint, "why": why,
               "assumption": "a provisional allowance for one welded joint and its dressing"}
    out["statement"] = f"{out['joint']}: {out['why']}"
    return out
