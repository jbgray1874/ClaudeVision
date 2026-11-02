"""The pack's GENERAL CONSTRUCTION note reaches the boards it describes (SCRUM-179).

12678-01-GA states "GENERAL CONSTRUCTION MDF - LAMINATED CLEAF TARANTA FD10" on the GA,
and the estimate carried none of it: the parts table has no material column, the title
block read WOOD, four boards were costed as raw TIMBER at raw-MDF sheet money, the
laminate appeared nowhere, and EDGE sat at zero hours on a retail podium whose every
visible face is faced. The note is the drawing office stating the whole product's
build-up once — exactly the shape of fact a per-part reader cannot see, and exactly what
the faced-board promotion (D-512's neighbour at estimator._faced_board_promotion) needs
as evidence: the board is bought pre-faced, the laminating is in the sheet price.

TWO CAREFUL LIMITS, both learned elsewhere in this codebase:

REFINE, NEVER CONTRADICT. Only a part whose material is the bare family word (WOOD,
TIMBER, or nothing at all) takes the note's board. A part whose own sheet prints OAK, or
PLYWOOD, or 304 stainless keeps it — the note describes the general construction, and a
part that states its own is the exception the word GENERAL already allows for.

THE NOTE'S OWN WORDS TRAVEL, NOT AN INVENTED FIELD. The laminate is stamped as
construction_note_laminate, carrying the sentence as printed, so the promotion can cite
"the pack's general construction note ('MDF - LAMINATED CLEAF TARANTA FD10')" rather
than pretending a material field said MFMDF outright. A note the promotion cannot turn
into a faced family (a laminated ply, a core with no catalogue) becomes an estimator
question on the part instead of silently pricing raw board — see estimate_material.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# The note, squashed to one line. The GA prints it as three stacked lines ("GENERAL
# CONSTRUCTION" / "MDF - LAMINATED" / "CLEAF TARANTA FD10"), so the capture runs across
# what used to be newlines and is cut at the next spec heading rather than at a length.
_RE_NOTE = re.compile(r"GENERAL\s+CONSTRUCTION\s*[:\-]?\s*(.{3,120})", re.I)
_STOPS = re.compile(
    r"\s+(?:GENERAL\s|FINISH(?:ES)?\b|WELD\b|TOLERAN|FIXED\s+SHELVES|ALL\s+DIMENSIONS|"
    r"DO\s+NOT\b|THIS\s+DRAWING|DRAWING\s+No|MAX\s+LOADING|WEIGHT\b|SPECIFICATION\b|"
    r"COPYRIGHT\b|PROJECT\b|SCALE\b|REV\b|DATE\b|DRAWN\b|CHECKED\b).*$", re.I)

# The board the note names, most specific first, so "MFMDF" is never read as "MDF".
_BOARDS = ("MFMDF", "MFC", "MDF", "PLYWOOD", "PLYWD", "PLY", "CHIPBOARD", "OSB")
# A bare family word a note may refine; a species or a named board is a statement.
_GENERIC_WOOD = {"", "WOOD", "TIMBER"}

_RE_LAM = re.compile(r"LAMINAT(?:ED|E)?\s*[:\-]?\s*", re.I)


def read(summary: Any) -> Optional[Dict[str, Any]]:
    """The first GENERAL CONSTRUCTION note on any sheet, or None.

    {"text": the note as printed (squashed), "board": the board family word it names or
    None, "laminated": bool, "where": "page N"}."""
    pages = ((summary or {}).get("pages") or []) if isinstance(summary, dict) else []
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        text = " ".join(" ".join(str(pg.get(k) or "") for k in
                                 ("pypdf_text", "pdfplumber_text", "normalized_text")).split())
        m = _RE_NOTE.search(text)
        if not m:
            continue
        stated = _STOPS.sub("", m.group(1)).strip(" .;:-")
        if not stated:
            continue
        up = stated.upper()
        board = next((b for b in _BOARDS if re.search(rf"\b{b}\b", up)), None)
        n = pg.get("job_page_number") or pg.get("page_number")
        return {"text": stated, "board": board,
                "laminated": bool(_RE_LAM.search(up)),
                "where": f"page {n}" if n else "its own sheet"}
    return None


def _skip(part: Dict[str, Any]) -> bool:
    if not isinstance(part, dict):
        return True
    if part.get("is_assembly_parent") or part.get("is_sub_assembly") \
            or (part.get("route_context") or {}).get("is_assembly_parent"):
        return True
    try:
        from part_code_conventions import carries_assembly_role
        if carries_assembly_role(part.get("part_number")):
            return True
    except Exception:                                                # noqa: BLE001
        pass
    try:
        from bought_in_policy import is_bought_in
        return bool(is_bought_in(part))
    except Exception:                                                # noqa: BLE001
        return False


def apply(note: Dict[str, Any], parts: Any) -> List[str]:
    """Stamp the note onto the made wood parts it describes; the part numbers touched.

    The board refines a bare family word; the laminate rides as the note's own words so
    the faced-board promotion and the workbook's edging question can cite it."""
    if not isinstance(note, dict):
        return []
    board = str(note.get("board") or "").upper()
    touched: List[str] = []
    for part in parts or ():
        if _skip(part):
            continue
        cur = str(part.get("normalized_material") or "").strip().upper()
        wood = cur in _GENERIC_WOOD or cur in ("MDF", "PLYWOOD", "MFMDF", "MFC",
                                               "CHIPBOARD", "OSB")
        if not wood:
            continue
        did = False
        if board and board not in ("PLY", "PLYWD") and cur in _GENERIC_WOOD:
            _was = part.get("normalized_material")
            part["normalized_material"] = board   # precedence: direct-write ok — refines the same pack's own bare family word (WOOD/TIMBER), never a part's stated material; a stated reading still lands through the resolver
            try:
                from source_precedence import _observe
                _observe(part, "normalized_material", _was or "",
                         "title block family word", applied=False,
                         displaced_by="the GA's general construction note")
            except Exception:                                        # noqa: BLE001
                pass
            part.setdefault("review_flags", []).append(
                f"material {_was or 'unset'} -> {board}: the GA's general construction "
                f"note states '{note.get('text')}' ({note.get('where')}), and this "
                f"part's own sheet states only the family word")
            did = True
        if note.get("laminated") and not part.get("construction_note_laminate"):
            part["construction_note_laminate"] = str(note.get("text") or "")
            did = True
        if did:
            touched.append(str(part.get("part_number") or ""))
    return touched
