"""A laminated board is its core plus its laminate (JG, 10 Nov 2026, 12674-01-GA).

The GA states "MATERIAL: SEE PART DRAWINGS  FINISH: WALNUT LAMINATE", and its parts' models
measure 19.6, 31.6, 43.6 and 12.8 mm: no stock board is any of those, so the catalogue matched
nothing and the dividers, shelves and false top were costed at £0, and the laminate nowhere.
JG: "price them as core board plus walnut laminate."

So, for a board part (MDF, MFC, ply, chipboard, by its own material words) where the part or the
drawing that draws it states a LAMINATE finish:

  * the GA's stated finish reaches a part that states none of its own (the general arrangement's
    FINISH box is the finish of the parts it does not send elsewhere);
  * a finished thickness that is not a stock board, but is one less a laminate on both faces
    (SDI_LAMINATE_THICKNESS_MM, default 0.8), or failing that on one face, is that core with the
    laminate on those faces: 31.6 is 30 mm board + 2 x 0.8, 12.8 is 12 mm + 1 x 0.8;
  * the board is priced at the core, the laminate is charged by area on those faces
    (applied_finish), and the part says so: finished thickness, core, faces, from what.

A thickness that no stock core explains is left as measured and said, never forced to the
nearest board. Provisional throughout: the part drawings, not in the pack, are the authority.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

STOCK_BOARD_MM_DEFAULT = (3.0, 4.0, 6.0, 9.0, 12.0, 15.0, 18.0, 22.0, 25.0, 30.0, 38.0)
LAMINATE_MM_DEFAULT = 0.8
_FINISH_IN_TEXT = re.compile(
    r"\bFINISH\s*:\s*(.+?)(?=\s+(?:COLOU?R|MATERIAL|GENERAL|TOLERANCE|WEIGHT|SCALE|DRAWN|REV)\b"
    r"|\s*$)", re.IGNORECASE)


def _cfg(name: str, default: Any) -> Any:
    try:
        import config as _c
        v = getattr(_c, name, None)
    except Exception:                                                # noqa: BLE001
        v = None
    return v if v not in (None, "", ()) else default


def stock_boards() -> List[float]:
    return [float(x) for x in _cfg("BOARD_STOCK_THICKNESSES_MM", STOCK_BOARD_MM_DEFAULT)]


def laminate_mm() -> float:
    import os
    try:
        return float(os.getenv("SDI_LAMINATE_THICKNESS_MM") or _cfg("LAMINATE_THICKNESS_MM",
                                                                     LAMINATE_MM_DEFAULT))
    except (TypeError, ValueError):
        return LAMINATE_MM_DEFAULT


def _is_stock(t: float, boards: Iterable[float]) -> bool:
    return any(abs(t - b) <= 0.05 for b in boards)


def core_of(finished_mm: Any, boards: Optional[Iterable[float]] = None,
            lam_mm: Optional[float] = None) -> Optional[Dict[str, float]]:
    """{core_mm, faces} when the finished thickness is a stock board plus laminate on two faces,
    or failing that on one; None when it is already a stock board or nothing explains it."""
    try:
        t = float(finished_mm)
    except (TypeError, ValueError):
        return None
    boards = list(boards if boards is not None else stock_boards())
    lam = laminate_mm() if lam_mm is None else lam_mm
    if t <= 0 or _is_stock(t, boards):
        return None
    for faces in (2, 1):
        core = round(t - faces * lam, 2)
        if core > 0 and _is_stock(core, boards):
            return {"core_mm": core, "faces": faces, "laminate_mm": lam}
    return None


def stated_finish(pages: Iterable[Dict[str, Any]]) -> str:
    """The FINISH the drawing pack's own title blocks state, where it names a laminate."""
    for page in pages or ():
        for key in ("pdfplumber_text", "normalized_text", "text_preview"):
            text = " ".join(str(page.get(key) or "").split())
            for m in _FINISH_IN_TEXT.finditer(text):
                value = m.group(1).strip(" .;,")
                if value and re.search(r"\bLAMINAT", value, re.IGNORECASE):
                    return value
    return ""


def _is_board(part: Dict[str, Any]) -> bool:
    try:
        import board_specification as bs
    except Exception:                                                # noqa: BLE001
        return False
    words = " ".join(str(part.get(k) or "") for k in ("normalized_material", "material",
                                                      "material_stated"))
    return bool(bs.substrates_in(words.replace("_", " ")))


def _own_finish(part: Dict[str, Any]) -> str:
    return " ".join(str(part.get(k) or "") for k in ("normalized_finish", "surface_finish")).strip()


def apply(parts: List[Dict[str, Any]], pages: Iterable[Dict[str, Any]]) -> List[str]:
    """Read each laminated board part as core plus laminate, in place. Returns what was said."""
    job_finish = stated_finish(pages)
    said: List[str] = []
    for p in parts or []:
        if not isinstance(p, dict) or not _is_board(p):
            continue
        finish = _own_finish(p)
        if not re.search(r"\bLAMINAT", finish, re.IGNORECASE):
            if not job_finish or finish:
                continue
            p["surface_finish"] = job_finish
            p["surface_finish_source"] = "general arrangement FINISH box"
            finish = job_finish
        t = p.get("normalized_thickness_mm")
        core = core_of(t)
        pn = p.get("part_number") or "?"
        if core:
            p["finished_thickness_mm"] = float(t)
            p["normalized_thickness_mm"] = core["core_mm"]  # precedence: direct-write ok — the measured finished thickness is kept as finished_thickness_mm; the priced board is the core derived from it, not a competing reading
            p["applied_finish_faces"] = core["faces"]
            p["laminated_construction"] = {
                **core, "finished_mm": float(t), "finish": finish, "provisional": True,
                "basis": (f"{float(t):g} mm finished = {core['core_mm']:g} mm board + "
                          f"{core['laminate_mm']:g} mm laminate on {core['faces']} face"
                          f"{'s' if core['faces'] > 1 else ''}; the part drawing is the authority")}
            p.setdefault("flags", []).append(
                f"laminated board: {p['laminated_construction']['basis']} (provisional)")
            said.append(f"{pn}: {p['laminated_construction']['basis']}")
        elif t is not None and not _is_stock(float(t), stock_boards()):
            p.setdefault("flags", []).append(
                f"laminated board: {float(t):g} mm finished is no stock board with "
                f"{laminate_mm():g} mm laminate on one or two faces — priced as measured; the part "
                f"drawing should state the build")
            said.append(f"{pn}: {float(t):g} mm explained by no stock core — said, not forced")
    return said
