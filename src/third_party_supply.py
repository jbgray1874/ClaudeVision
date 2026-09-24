"""Items the drawing says somebody else supplies are listed at £0, not priced as ours.

12312-01-GA (Tesco IMS digital header), Rev B: the GA carries "display, router and antenna
supplied and fitted by Pixel Inspiration UK". The BOM still lists the three — the Bluefin
49.1" LCD (20-0129-0365), the Teltonika RUT200 and the puck antenna — because they are in
the product. Priced down the ordinary waterfall, a 49" commercial display is a four-figure
researched market figure and dominates a unit whose steel case is the job.

The note is the drawing's own statement of scope. This reads it: a clause of the form
"<items> SUPPLIED [AND FITTED] BY <party>" (or PROVIDED BY / FREE ISSUED BY), where the party
is not SDI, names items; a BOUGHT-IN line whose description names one of those items is
marked as supplied by that party and costed at £0 with the party on the line. Everything
SDI makes is protected three ways — fabrication evidence, an SDI detail code, or a
structural noun in its description (the 02M DISPLAY BRACKET and 05M ROUTER MOUNT PLATE are
ours) — so a note about a screen can never zero the bracket that holds it.

Nothing is dropped: the line stays on the sheet so the pack is complete, and the estimator
can overturn it by pricing the line.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    import config
except Exception:                                                     # pragma: no cover
    config = None                                                     # type: ignore

_CLAUSE = re.compile(
    r"(?P<items>[A-Z0-9][A-Z0-9 ,&/'\"().-]{2,160}?)\s+"
    r"(?:(?:TO\s+BE|ARE|IS|WILL\s+BE)\s+)?"
    r"(?:SUPPLIED\s*(?:AND|&)\s*(?:FITTED|INSTALLED)|SUPPLIED|PROVIDED|FREE[\s-]*ISSUED?)"
    r"\s+BY\s+(?P<party>[A-Z][A-Z0-9 &.'-]{1,60})")

_STOP = {"THE", "ALL", "AND", "ANY", "WITH", "NOTE", "NOTES", "ITEMS", "ITEM", "UNIT",
         "UNITS", "PART", "PARTS", "SEE", "PLEASE", "ONLY", "ARE", "IS"}

# What a supplied item may be called on a BOM line. Generic hardware vocabulary; extend in
# config.THIRD_PARTY_ITEM_SYNONYMS.
_SYNONYMS = {
    "DISPLAY": ("DISPLAY", "SCREEN", "LCD", "LED SCREEN", "MONITOR", "TV", "PANEL PC"),
    "SCREEN": ("DISPLAY", "SCREEN", "LCD", "MONITOR", "TV"),
    "ROUTER": ("ROUTER", "RUT", "MODEM"),
    "ANTENNA": ("ANTENNA", "AERIAL"),
    "MEDIA PLAYER": ("MEDIA PLAYER", "PLAYER"),
    "TABLET": ("TABLET", "IPAD"),
}

# A line naming any of these is something SDI makes to hold, mount or cover the item.
_STRUCTURAL = ("BRACKET", "MOUNT", "PLATE", "CHANNEL", "PANEL", "HOLDER", "SUPPORT", "COVER",
               "FRAME", "CASE", "HOUSING", "BOX", "SHELF", "TRAY", "CLIP", "GRAPHIC", "FASCIA",
               "SIDE", "TOP", "BOTTOM", "BACK", "LOCK", "HANGER", "SPACER")

_SDI_DETAIL_CODE = re.compile(r"-\d{2,3}[A-Z]{1,2}(?:[-\s]?(?:H|HANDED|MIR|MIRROR))?$")


def supply_notes(texts: Iterable[str]) -> List[Dict[str, Any]]:
    """Every "<items> supplied by <party>" clause in the drawing text, SDI's own excluded."""
    found: List[Dict[str, Any]] = []
    blob = " ".join(str(t or "") for t in texts).upper()
    for sentence in re.split(r"[.;\n]+|\s(?=\d{1,2}[.)]\s)", blob):
        s = " ".join(sentence.split())
        for m in _CLAUSE.finditer(s):
            party = re.split(r"\s{2,}|,|\bFOR\b|\bON\b|\bAT\b", m.group("party"))[0].strip(" .-")
            if not party or "SDI" in party.split():
                continue
            items_text = m.group("items")
            items_text = re.split(r":|\bNOTE\s*\d*\b", items_text)[-1]
            items = []
            for chunk in re.split(r",|\bAND\b|&|/", items_text):
                words = [w for w in re.findall(r"[A-Z0-9][A-Z0-9'\"-]*", chunk)
                         if w not in _STOP and len(w) > 1]
                if words:
                    items.append(" ".join(words[-2:]))
            if items:
                found.append({"items": items, "party": party, "clause": s[:200]})
    return found


def _synonyms(item: str) -> List[str]:
    extra = dict(getattr(config, "THIRD_PARTY_ITEM_SYNONYMS", {}) or {}) if config else {}
    for key, words in list(_SYNONYMS.items()) + list(extra.items()):
        if key in item.split() or key == item:
            return list(words)
    return [item]


def _names_item(description: str, item: str) -> bool:
    d = f" {description.upper()} "
    for w in _synonyms(item):
        if re.search(rf"(?<![A-Z]){re.escape(w)}(?![A-Z])", d):
            return True
    return False


def _is_ours(part: Mapping[str, Any]) -> bool:
    pn = str(part.get("part_number") or "").strip().upper()
    if _SDI_DETAIL_CODE.search(pn):
        return True
    if part.get("is_assembly_parent") or part.get("is_sub_assembly") or part.get("assembly_children"):
        return True
    try:
        from bought_in_policy import has_fabrication_evidence
        if has_fabrication_evidence(dict(part)):
            return True
    except Exception:                                                 # noqa: BLE001
        pass
    desc = str(part.get("description") or "").upper()
    return any(re.search(rf"(?<![A-Z]){w}S?(?![A-Z])", desc) for w in _STRUCTURAL)


def mark_third_party_supplied(parts: List[Dict[str, Any]],
                              summary: Optional[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Mark the bought-in lines the drawing says another party supplies. Returns what it marked."""
    if not isinstance(summary, Mapping):
        return []
    texts: List[str] = []
    for pg in summary.get("pages") or []:
        if isinstance(pg, Mapping):
            texts.append(str(pg.get("pdfplumber_text") or ""))
            texts.append(str(pg.get("normalized_text") or ""))
    notes = supply_notes(texts)
    if not notes:
        return []
    marked: List[Dict[str, str]] = []
    for p in parts or []:
        if not isinstance(p, dict) or p.get("supplied_by_third_party") or _is_ours(p):
            continue
        desc = " ".join(str(p.get(k) or "") for k in ("description", "part_number"))
        for n in notes:
            hit = next((i for i in n["items"] if _names_item(desc, i)), None)
            if hit:
                p["supplied_by_third_party"] = n["party"]
                p.setdefault("risk_flags", []).append("customer_supplied_zero_cost")
                p.setdefault("review_flags", []).append(
                    f"supplied by {n['party'].title()} per the drawing ('{n['clause'][:120]}') — "
                    f"listed at £0 so the pack is complete. If SDI is buying it, price the line.")
                marked.append({"part_number": str(p.get("part_number") or ""),
                               "item": hit, "party": n["party"]})
                break
    for m in marked:
        print(f"   [scope] {m['part_number']} supplied by {m['party'].title()} "
              f"(drawing note names '{m['item']}') — listed at £0", flush=True)
    return marked
