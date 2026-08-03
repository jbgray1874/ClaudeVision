"""
part_identity.py — tolerant part-number / BOM / DXF identity for SDI drawing packs.

Drawing packs routinely use different labels for the same physical item (bay BOM,
detail title block, DXF filename). This module centralises normalisation and
alias resolution so estimators can cope without requiring FD to rename everything first.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# DXF filename / legacy drawing numbers -> BOM detail part
DXF_TO_BOM_ALIASES: Dict[str, str] = {
    "1148": "1448-02",
    "1453-01C": "1453-GA-C",
    "1453": "1453-GA-C",
}

# Assembly / GA codes -> preferred fab detail when only one child exists in scope
GA_TO_DETAIL_PREFERENCE: Dict[str, str] = {
    "1450": "1450-01C",
    "1450-GA": "1450-01C",
    "1453": "1453-01C",
    "1453-GA": "1453-01C",
    "1453-GA-C": "1453-01C",
    "1453-GAC": "1453-01C",
}

# Catalogue tokens: extra description phrases tried against the parts DB / price book
CATALOGUE_DESC_ALIASES: Dict[str, List[str]] = {
    "ELECTRICS": [
        "ELECTRICS 50CM LOOM LIGHTING ELECTRICS",
        "50CM LOOM LIGHTING ELECTRICS",
        "LOOM LIGHTING ELECTRICS",
        "50CM LOOM",
    ],
}

_SPLIT_KICK_RE = re.compile(
    r"(\d+)\s+1453-GA-\s+([A-Z])\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
    re.IGNORECASE,
)
_GA_WALL_RE = re.compile(
    r"(\d+)\s+(3886-GA-)\s+WALL\s+(BAY\s+BUDGET\s+LOWER\s+LEG)\s+(\d+)\b",
    re.IGNORECASE,
)
_HEADER_GA_RE = re.compile(
    r"(\d+)\s+(1455-C-)\s+GA\s+(500mm\s+MILWAUKEE\s+HEADER)\s+(\d+)\b",
    re.IGNORECASE,
)
_KICK_ROW_RE = re.compile(
    r"(\d+)\s+(1453-GA-C?)\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
    re.IGNORECASE,
)


def split_catalogue_token(code: str) -> str:
    """ELECTRICS50CM -> ELECTRICS (BOM tokens glued to size suffixes)."""
    c = str(code or "").strip().upper().replace(" ", "")
    m = re.match(r"^(ELECTRICS)(50CM|100CM|1M)(.*)$", c, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return c


def normalize_part_code(raw: Any) -> str:
    """Canonical part code: collapse spaces, join spaced GA tokens, strip trailing '-'."""
    s = str(raw or "").strip().upper()
    if not s:
        return ""
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    # "1450 - GA" / "1450 GA" -> 1450-GA
    m = re.match(r"^(\d{4})\s+(?:-\s*)?GA([A-Z]?)$", s, re.IGNORECASE)
    if m:
        suffix = m.group(2).upper()
        return f"{m.group(1)}-GA{suffix}" if suffix else f"{m.group(1)}-GA"
    m = re.match(r"^(\d{4}-[A-Z0-9]+)\s+GA([A-Z]?)$", s, re.IGNORECASE)
    if m:
        suffix = m.group(2).upper()
        base = m.group(1).upper()
        return f"{base}-GA{suffix}" if suffix else f"{base}-GA"
    s = s.replace(" ", "")
    s = re.sub(r"-+$", "", s)
    s = re.sub(r"-(?!GA$|CGA$)[A-Z]{3,}$", "", s)  # strip trailing desc bleed e.g. -WALL
    if s and s[0].isalpha():
        s = split_catalogue_token(s)
    return s


# Codes a drawing prints where it has no code to print. They are not identities, and a
# BOM line carrying one must never become the canonical target another line merges INTO:
# on job 11350 the M4 wing nut was absorbed into a part numbered "-", which then appeared
# in the hierarchy and in the assembly route as a participant.
_PLACEHOLDER_CODES = frozenset({
    "", "-", "--", "---", ".", "N/A", "NA", "TBC", "TBA", "NONE", "?", "X", "XX",
})


def is_placeholder_identity(part_number: Any) -> bool:
    """True when a code says 'no code', rather than naming a part."""
    text = str(part_number or "").strip().upper()
    if text in _PLACEHOLDER_CODES:
        return True
    # A code made only of separators is the same statement in another form.
    return bool(text) and not re.search(r"[A-Z0-9]", text)


def dxf_alias_target(part_number: str) -> Optional[str]:
    key = normalize_part_code(part_number)
    return DXF_TO_BOM_ALIASES.get(key)


def resolve_estimate_code(
    code: str,
    description: str,
    available: Iterable[str],
) -> Optional[str]:
    """Map a BOM / GA code to a per-part estimate key when labels differ."""
    norm = normalize_part_code(code)
    if not norm:
        return None
    avail = {normalize_part_code(c): c for c in available if c}
    if norm in avail:
        return avail[norm]

    pref = GA_TO_DETAIL_PREFERENCE.get(norm)
    if pref:
        pn = normalize_part_code(pref)
        if pn in avail:
            return avail[pn]

    # 1450-GA style: numeric prefix + detail suffix in scope
    prefix_m = re.match(r"^(\d{4})(?:-GA.*)?$", norm)
    if prefix_m:
        prefix = prefix_m.group(1)
        children = [
            avail[k]
            for k in avail
            if k.startswith(prefix + "-") and not k.endswith("-GA") and "-GA" not in k[5:]
        ]
        if len(children) == 1:
            return children[0]

    # Kick / peg families by description when GA code missing
    desc_u = str(description or "").upper()
    if "KICK" in desc_u and "PLATE" in desc_u:
        for key in ("1453-01C", "1453-GA-C", "1453-GA"):
            pn = normalize_part_code(key)
            if pn in avail:
                return avail[pn]
    if "PEG PANEL" in desc_u and "HALF" not in desc_u:
        if "1449-01C" in avail.values() or normalize_part_code("1449-01C") in avail:
            return avail.get(normalize_part_code("1449-01C"))
    if "HALF" in desc_u and "PEG" in desc_u:
        pn = normalize_part_code("2621-01C")
        if pn in avail:
            return avail[pn]

    return None


def preprocess_bom_text(text: str) -> str:
    """Repair common OCR/layout splits before BOM regex extraction."""
    if not text:
        return text
    t = re.sub(r"\s+", " ", str(text))

    t = _SPLIT_KICK_RE.sub(r"\1 1453-GA-\2 \3 \4", t)
    t = _GA_WALL_RE.sub(r"\1 3886-GA WALL \3 \4", t)
    t = _HEADER_GA_RE.sub(r"\1 1455-C-GA \3 \4", t)

    # "1453-GA- 4 500mm..." — digit is item no, not revision letter
    t = re.sub(
        r"\b1453-GA-\s+(\d+)\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
        r"\1 1453-GA-C \2 \3",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\bELECTRICS\s*50\s*CM\b", "ELECTRICS 50CM", t, flags=re.IGNORECASE)
    t = re.sub(r"\bELECTRICS50CM\b", "ELECTRICS 50CM", t, flags=re.IGNORECASE)
    return t


def normalize_bom_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    pn = normalize_part_code(row.get("part_number"))
    if pn:
        out["part_number"] = pn
    desc = str(row.get("description") or "").strip()
    if pn == "3886-GA" and desc.upper().startswith("WALL"):
        out["description"] = desc[4:].strip() or "WALL BAY BUDGET LOWER LEG"
    return out


def inject_missing_bay_rows(rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add top-level bay lines that layout/OCR dropped (e.g. split kick plate row)."""
    out = [normalize_bom_row(r) for r in rows]
    codes = {normalize_part_code(_row_code(r)) for r in out}

    blob_parts: List[str] = []
    for page in summary.get("pages") or []:
        blob_parts.append(page.get("normalized_text") or "")
        blob_parts.append(page.get("pdfplumber_text") or "")
    blob = preprocess_bom_text(" ".join(blob_parts))

    for m in _KICK_ROW_RE.finditer(blob):
        item, pn, desc, qty = m.groups()
        code = normalize_part_code(pn)
        if not code or code in codes:
            continue
        out.append(
            {
                "item_number": item,
                "part_number": code if code.startswith("1453") else "1453-GA-C",
                "description": desc.strip(),
                "quantity": int(qty),
                "source": "bay_bom_stitch",
            }
        )
        codes.add(normalize_part_code("1453-GA-C"))

    return out


def _row_code(row: Dict[str, Any]) -> str:
    return normalize_part_code(row.get("part_number") or row.get("code") or "")


def catalogue_search_descriptions(code: str, desc: str) -> List[str]:
    c = normalize_part_code(code) or str(code or "").strip().upper()
    d = str(desc or "").strip()
    variants = [d, f"{c} {d}".strip(), c]
    variants.extend(CATALOGUE_DESC_ALIASES.get(c, []))
    seen: Set[str] = set()
    out: List[str] = []
    for v in variants:
        key = v.upper()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def score_dxf_candidate(part: Dict[str, Any], path: Any, *, cut_length_mm: float = 0.0) -> float:
    """Prefer credible peg/spigot flats when several DXFs share a numeric family."""
    from pathlib import Path

    p = Path(path)
    name = p.name.upper()
    pn = normalize_part_code(part.get("part_number") or "")
    score = 0.0
    if "PEG" in name and "1449" in pn:
        score += 3.0
        if "50CM" in name or "500" in name:
            score += 2.0
        if cut_length_mm >= 2500:
            score += 2.0
        elif cut_length_mm < 1800:
            score -= 2.0
    if "SPIGOT" in name and pn == "1448-02":
        score += 4.0
    if "1148" in name and pn == "1448-02":
        score += 4.0
    if "KICK" in name and "1453" in pn:
        score += 4.0
    if "1450" in pn and ("BASE" in name or "PLATE" in name):
        score += 2.0
        desc_digits = "".join(c for c in str(part.get("description") or "") if c.isdigit())
        prefer_650 = "650" in desc_digits
        if "650" in name:
            score += 4.0 if prefer_650 else -4.0
        if "500" in name or "50CM" in name:
            score += -1.0 if prefer_650 else 3.0
        if "REV" in name and "500" not in name and "650" not in name:
            score -= 0.5
    return score
