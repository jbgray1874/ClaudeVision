"""The adhesive and wax a glued board assembly uses, priced as its share of a pack (D-723).

11908-22-GA, 5 Nov 2026: an oak-laminated MDF tray of five panels, mitred and rebated, glued
together, its corner gaps filled with matching wax as the GA states. The CNC and bench rows
covered the work, but neither the joint adhesive nor the wax was on the bill. A reviewer:
"check that necessary adhesive and wax consumables are included"; JG: add them.

The rule, generic:
  * an assembly whose own children include two or more board pieces (MDF, faced MDF, MFC,
    chipboard, ply, timber) is glued, unless glue is already on its route or its bill: it
    carries an ADHESIVE line, a share of one adhesive pack per board piece glued;
  * an assembly whose pack names wax (a note such as "FILL ANY OPEN GAPS ON CORNERS WITH
    MATCHING WAX") carries a WAX line, a share of one filler pack per assembly.

The shares are HOUSE ALLOWANCES in config (BOARD_ASSEMBLY_CONSUMABLES), stated on every line;
the money is the pack's own price from SDI's sources (estimator._consumable_share_cost), so a
line is never a whole tin per unit. A pack nobody can price leaves the line unpriced and asked,
never a market guess for a whole tin.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

WOOD_BOARDS = ("MDF", "MFMDF", "MFC", "CHIPBOARD", "PLYWOOD", "PLY", "TIMBER", "OSB")
_GLUE_WORDS = ("ADHESIVE", "GLUE", "PVA", "EPOXY")


def _cfg() -> Dict[str, Any]:
    try:
        import config
        return dict(getattr(config, "BOARD_ASSEMBLY_CONSUMABLES", {}) or {})
    except Exception:                                                # noqa: BLE001
        return {}


def _key(v: Any) -> str:
    return re.sub(r"[\s\-_./]+", "", str(v or "")).upper()


def _is_board(part: Dict[str, Any]) -> bool:
    mat = str(part.get("normalized_material") or "").upper().replace("_", " ")
    return any(re.search(rf"\b{w}\b", mat) for w in WOOD_BOARDS)


def _already_glued(asm: Dict[str, Any], members: List[Dict[str, Any]],
                   parts: List[Dict[str, Any]]) -> bool:
    for p in [asm] + members:
        ops = {str(o).lower() for o in ((p.get("textual_operations") or [])
                                        + (p.get("inferred_operations") or [])
                                        + (p.get("operations") or []))}
        if "glue" in ops or "gluing" in ops:
            return True
    for p in parts:
        if not isinstance(p, dict) or p.get("_consumable_share_line"):
            continue
        parent = _key(p.get("bom_parent") or p.get("owning_assembly"))
        if parent and parent == _key(asm.get("part_number")) and any(
                w in str(p.get("description") or "").upper() for w in _GLUE_WORDS):
            return True
    return False


def _pack_says_wax(summary: Any) -> str:
    for pg in ((summary or {}).get("pages") or []) if isinstance(summary, dict) else []:
        if not isinstance(pg, dict):
            continue
        text = " ".join(str(pg.get(k) or "") for k in ("pdfplumber_text", "pypdf_text",
                                                       "normalized_text", "text"))
        for line in re.split(r"[\r\n]+", text):
            if re.search(r"\bWAX\b", line, re.I):
                return " ".join(line.split())[:120]
    return ""


def mint(parts: Any, summary: Any) -> List[str]:
    """Add the adhesive and wax lines each glued board assembly needs. Returns codes minted."""
    cfg = _cfg()
    if not cfg.get("enabled") or not isinstance(parts, list):
        return []
    by_key = {_key(p.get("part_number")): p for p in parts if isinstance(p, dict)}
    wax_note = _pack_says_wax(summary)
    minted: List[str] = []
    for asm in list(parts):
        if not isinstance(asm, dict) or not asm.get("assembly_children"):
            continue
        members = [by_key.get(_key(c)) for c in asm.get("assembly_children") or []]
        members = [m for m in members if isinstance(m, dict)]
        boards = [m for m in members if _is_board(m) and not m.get("assembly_children")]
        pieces = 0.0
        for m in boards:
            try:
                pieces += float(m.get("quantity") or 1)
            except (TypeError, ValueError):
                pieces += 1
        if pieces < 2:
            continue
        apn = str(asm.get("part_number") or "").strip()
        lines = []
        rule = cfg.get("adhesive") or {}
        if rule and not _already_glued(asm, members, parts):
            count = round(float(rule.get("share_per_piece") or 0) * pieces, 4)
            lines.append(("ADHESIVE", rule, count,
                          f"{rule.get('share_per_piece'):g} of a pack per board piece glued x "
                          f"{pieces:g} piece(s)"))
        rule_w = cfg.get("wax") or {}
        if rule_w and wax_note:
            lines.append(("WAX", rule_w, round(float(rule_w.get("share_per_assembly") or 0), 4),
                          f"{rule_w.get('share_per_assembly'):g} of a pack per assembly; the "
                          f"pack says '{wax_note}'"))
        for tag, r, count, working in lines:
            pn = f"{apn}-{tag}"
            if count <= 0 or _key(pn) in by_key:
                continue
            rec = {
                "part_number": pn, "description": str(r.get("description") or tag.title()),
                "quantity": 1.0, "is_bought_in": True, "page_roles": ["bought_in"],
                "pages": [], "materials": [], "source": "board_assembly_consumable",
                "bom_parent": apn, "owning_assembly": apn, "_consumable_share_line": True,
                "consumable_share": {"reference_item": str(r.get("reference_item") or ""),
                                     "count": count, "working": working,
                                     "basis": str(r.get("basis") or "house allowance"),
                                     # The pack's mass and SDI's own rows to price it by
                                     # (D-725); absent on a rule that is priced by the pack.
                                     "pack_kg": r.get("pack_kg"),
                                     "catalogue_specs": list(r.get("catalogue_specs") or [])},
                "review_flags": [
                    f"CONSUMABLE ALLOWANCE, PROVISIONAL: {r.get('description')} for {apn} — "
                    f"{working} = {count:g} x '{r.get('reference_item')}'. "
                    f"{r.get('basis') or 'A house allowance to confirm'}"],
            }
            parts.append(rec)
            by_key[_key(pn)] = rec
            minted.append(pn)
    return minted
