"""
bom_quantity_audit.py  —  first increment of "GA BOM as the single source of truth".

The costing rollup in bay_rollup already propagates an assembly parent's quantity
to its children (assembly_of_N_parts: line_cost = sum(child unit) * parent_qty).
The leg-qty bug happens *upstream*: when a `…-GA` assembly row never reaches
bom_rows, its children aren't shadowed under it and silently fall back to qty 1.

This module turns that silent fallback into a loud, auditable flag: it checks that
every fabricated detail part is *governed* by the BOM — either by its own BOM row
(explicit qty) or by an assembly parent row that shares its number family. Any
part that is governed by neither has had its per-bay quantity defaulted, and is
flagged for review instead of quietly costing at 1.

This is read-only — it raises visibility, it does not change any cost. Once the
GA-row capture is fixed, the governed parts stop flagging on their own.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List
import re

_ASSEMBLY_SUFFIX = re.compile(r"-(GA|WA\d*|WELD(?:MENT)?)\b", re.IGNORECASE)


def _norm(code: Any) -> str:
    return re.sub(r"\s+", "", str(code or "")).upper()

def _numeric_prefix(code: str) -> str:
    m = re.match(r"(\d{3,})", _norm(code))
    return m.group(1) if m else ""

def _is_assembly(code: str, desc: str = "") -> bool:
    return bool(_ASSEMBLY_SUFFIX.search(_norm(code))) or "WELDMENT" in str(desc).upper()

def _row_code(r: Dict[str, Any]) -> str:
    return _norm(r.get("part_number") or r.get("code") or r.get("part_code"))

def _row_desc(r: Dict[str, Any]) -> str:
    return str(r.get("description") or "")

def _est_code(e: Dict[str, Any]) -> str:
    return _norm(e.get("part_number") or e.get("part_no") or e.get("code"))


def audit_quantity_governance(
    bom_rows: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return a flag per fabricated detail part whose per-bay quantity is not
    governed by any BOM row (its own, or an assembly parent in its number family)."""
    # codes that have their own explicit BOM row (own quantity stated)
    own_row_codes = {_row_code(r) for r in bom_rows if _row_code(r)}
    # assembly parent rows present in the BOM, indexed by number family prefix
    assembly_prefixes = {
        _numeric_prefix(_row_code(r))
        for r in bom_rows
        if _is_assembly(_row_code(r), _row_desc(r)) and _numeric_prefix(_row_code(r))
    }

    flags: List[Dict[str, Any]] = []
    for e in part_estimates:
        c = _est_code(e)
        if not c or _is_assembly(c, e.get("description", "")):
            continue  # assemblies are governed by their own rollup, not flagged
        if c in own_row_codes:
            continue  # explicit BOM row -> quantity is governed
        if _numeric_prefix(c) and _numeric_prefix(c) in assembly_prefixes:
            continue  # an assembly parent in the same family governs it
        flags.append({
            "severity": "warning",
            "code": c,
            "detail": (
                f"per-bay quantity for '{c}' is not governed by any BOM row "
                f"(no own line, no assembly parent in family {_numeric_prefix(c) or '?'}) "
                f"\u2014 it has defaulted to 1; confirm the per-bay quantity from the GA BOM"
            ),
        })
    return flags
