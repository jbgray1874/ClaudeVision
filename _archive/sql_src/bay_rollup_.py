"""
bay_rollup.py — SDI Intelligence full-bay (assembly) estimating.

ADDITIVE layer over the per-part estimator. It does NOT change per-part costing.
Given the top-level GA's BOM (the bay parts list) plus the per-part fab estimates
already produced by estimate_document, it:

  * binds each BOM line to a cost:
      - a fabricated detail part  -> the matching per-part estimate, at BOM qty
      - a sub-assembly (-GA / -C)  -> the SUM of its costed detail parts
      - a catalogue token (FIXING*, ELECTRICS*, *TUBE*, RIVET, INSERT, ...) ->
        priced via the catalogue/bought-in pricer
  * when an assembly has no detail drawings in scope, rolls up orphan prefix
    parts (e.g. kick flat 1453-01C under 1453-GA) or falls back to a GA-BOM
    provisional blank estimate (flagged low confidence — no DXF/detail GA)
  * flags LOUDLY any line with no credible cost and contributes 0 to that line
  * adds standard template lines (packaging) that never appear on a fab drawing
  * rolls everything up to a bay total at the order quantity

Design principles carried from the per-part engine:
  * No confident wrong number. Implausible catalogue matches are rejected.
  * Provisional GA-only costs are allowed but never promoted to the headline total.
  * Cost each part once, at its BOM quantity.
  * Suppress the bay headline total when provisional / uncosted lines remain.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


# ── BOM line classification ──────────────────────────────────────────────────

_CATALOGUE_PATTERNS = [
    r"\bFIXING\d*", r"\bELECTRIC", r"\bLOOM\b", r"\bRIVET\b", r"\bINSERT\b",
    r"\bCABLE\s*TIE", r"\bGROMMET\b", r"\bSCREW\b", r"\bBOLT\b", r"\bNUT\b",
    r"\bWASHER\b", r"\bSLOTTED\s*TUBE", r"\bTUBE\d+", r"\bVINYL", r"\bSUBPLAS",
    r"\bOPAL\b", r"\bPERSPEX\b", r"\bACRYLIC\b", r"\bHIPS\b", r"\bFOAM\b",
    r"\bTAPE\b", r"\bCLIP\b", r"\bGUIDE", r"\bBOX\d*", r"\bPALLET\b",
]
_CATALOGUE_RE = re.compile("|".join(_CATALOGUE_PATTERNS), re.IGNORECASE)

_CONSUMABLE_RE = re.compile(r"\bPOWDER", re.IGNORECASE)
_ASSEMBLY_SUFFIX_RE = re.compile(r"-(GA|SA\d*)$", re.IGNORECASE)
_WELDMENT_PARENT_RE = re.compile(r"-101$", re.IGNORECASE)
_CATALOGUE_BOM_ROW_RE = re.compile(
    r"\b(\d+)\s+(ELECTRICS(?:[-\s][A-Z0-9]+)?|FIXING\d+|SLOTTEDTUBE\d+|VINYL\d+|SUBPLAS\d+|POWDER\d+)\s+(.+?)\s+(\d+)\b",
    re.IGNORECASE,
)
_JUNK_ESTIMATE_CODES = frozenset({"C-001"})


def _norm_code(raw: Any) -> str:
    try:
        from part_identity import normalize_part_code

        return normalize_part_code(raw)
    except Exception:
        s = str(raw or "").strip().upper()
        if not s:
            return ""
        token = s.split()[0]
        token = re.sub(r"[^A-Z0-9\-]", "", token)
        return token


def _assembly_base(code: str) -> str:
    return _ASSEMBLY_SUFFIX_RE.sub("", code)


def classify_bom_line(code: str, description: str) -> str:
    blob = f"{code} {description}".upper()
    if _CONSUMABLE_RE.search(blob):
        return "consumable"
    if _CATALOGUE_RE.search(blob):
        return "catalogue"
    if code and code[0].isdigit():
        return "assembly" if _ASSEMBLY_SUFFIX_RE.search(code) else "detail"
    if code and code[0].isalpha():
        return "catalogue"
    return "detail"


# ── Field access (defensive: BOM rows vary by extractor) ─────────────────────

def _row_code(row: Dict[str, Any]) -> str:
    for k in ("part_number", "part_code", "code", "item", "description"):
        v = row.get(k)
        if v:
            c = _norm_code(v)
            if c:
                return c
    return ""


def _row_description(row: Dict[str, Any]) -> str:
    return str(row.get("description") or row.get("desc") or row.get("part_number") or "").strip()


def _row_qty(row: Dict[str, Any]) -> float:
    for k in ("quantity", "qty", "qty_per_bay", "qty_per_unit"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                continue
    return 1.0


def _est_code(est: Dict[str, Any]) -> str:
    return _norm_code(est.get("part_number") or est.get("item_number") or "")


def _est_unit_cost(est: Dict[str, Any]) -> Optional[float]:
    for k in ("unit_total_cost_gbp", "unit_cost_gbp", "total_unit_cost_gbp"):
        v = est.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _est_is_provisional(est: Dict[str, Any]) -> bool:
    ds = est.get("data_sufficiency") or {}
    if ds.get("status") == "insufficient_data":
        return True
    if est.get("geometry_inferred"):
        return True
    flags = est.get("review_flags") or []
    markers = (
        "geometry_inferred_provisional",
        "no_geometry",
        "provisional",
        "insufficient_data",
    )
    for f in flags:
        fs = str(f).lower()
        if any(m in fs for m in markers):
            return True
    basis = str((est.get("cost_breakdown") or {}).get("costing_basis") or "").lower()
    return "provisional" in basis or "inferred" in basis


def _line_confidence(*, provisional: bool) -> str:
    return "low" if provisional else "high"


def _numeric_prefix(code: str) -> str:
    m = re.match(r"^(\d+)", code or "")
    return m.group(1) if m else ""


def provisional_cost_from_ga_bom(description: str) -> Optional[Dict[str, Any]]:
    """Infer a rough unit cost from the GA BOM description when no detail set exists."""
    try:
        from geometry_inference import provisional_blank_from_description
    except Exception:
        return None
    blank = provisional_blank_from_description(description)
    if not blank:
        return None
    uc = _rough_fab_unit_cost_gbp(blank["length_mm"], blank["width_mm"])
    return {
        "unit_cost_gbp": uc,
        "source": "ga_bom_provisional",
        "confidence": 0.35,
        "inference_basis": blank.get("basis") or "category_default",
        "family": blank.get("family"),
        "blank_mm": (blank["length_mm"], blank["width_mm"]),
        "note": (
            f"Provisional from GA BOM description ({blank.get('family') or 'typical'} blank) — "
            "no detail drawing/DXF in scope; verify dimensions"
        ),
    }


def _rough_fab_unit_cost_gbp(length_mm: float, width_mm: float, *, thickness_mm: float = 1.5) -> float:
    """Conservative GA-only blank estimate — material + basic laser, not a quote."""
    area_m2 = max(0.0, length_mm * width_mm) / 1_000_000.0
    material = area_m2 * 7.85 * thickness_mm * 4.0
    laser = area_m2 * 15.0
    return round(material + laser + 2.0, 2)


def extract_catalogue_bom_rows_from_pages(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse bought-in tokens from assembly page text (ELECTRICS, FIXING*, etc.)."""
    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for page in summary.get("pages") or []:
        text = f"{page.get('normalized_text') or ''} {page.get('pdfplumber_text') or ''}"
        for match in _CATALOGUE_BOM_ROW_RE.finditer(text):
            item_no, code_raw, desc, qty_raw = match.groups()
            try:
                from part_identity import split_catalogue_token

                code = _norm_code(split_catalogue_token(code_raw))
            except Exception:
                code = _norm_code(code_raw)
            if not code or code in seen:
                continue
            seen.add(code)
            try:
                qty = max(1, int(qty_raw))
            except (TypeError, ValueError):
                qty = 1
            rows.append(
                {
                    "item_number": item_no,
                    "part_number": code,
                    "description": desc.strip(),
                    "quantity": qty,
                    "source": "assembly_text_catalogue",
                }
            )
    return rows


_BOM_SOURCE_PRIORITY = {
    "bay_bom": 0,
    "bay_bom_stitch": 1,
    "document_analysis": 2,
    "assembly_text_catalogue": 3,
    "folder_job_synthesized": 9,
}


def _assembly_child_codes(code: str, available: Iterable[str]) -> List[str]:
    """Detail part codes that a GA / assembly BOM line rolls up."""
    code = _norm_code(code)
    if not code:
        return []
    base = _assembly_base(code)
    prefix = _numeric_prefix(base or code)
    out: List[str] = []
    for raw in available:
        c = _norm_code(raw)
        if not c or c == code:
            continue
        if c.startswith(code + "-") or c == base or (base and c.startswith(base + "-")):
            if not _ASSEMBLY_SUFFIX_RE.search(c):
                out.append(c)
            continue
        if prefix and c.startswith(prefix + "-") and "-GA" not in c[5:]:
            if not _ASSEMBLY_SUFFIX_RE.search(c):
                out.append(c)
    return out


def codes_shadowed_by_parent_bom(bom_rows: List[Dict[str, Any]], est_codes: Iterable[str]) -> set:
    """Detail codes already costed via a parent GA / assembly BOM row — skip duplicate lines."""
    est_list = [_norm_code(c) for c in est_codes if _norm_code(c)]
    est_set = set(est_list)
    shadowed: set = set()
    for row in bom_rows:
        code = _row_code(row)
        if not code:
            continue
        desc = _row_description(row)
        kind = classify_bom_line(code, desc)
        if kind in ("catalogue", "consumable"):
            continue
        resolved = None
        try:
            from part_identity import resolve_estimate_code

            resolved = resolve_estimate_code(code, desc, est_list)
        except Exception:
            pass
        if resolved:
            shadowed.add(_norm_code(resolved))
            continue
        if _ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly":
            shadowed.update(_assembly_child_codes(code, est_set))
    return shadowed


def dedupe_bom_rows_for_bay_rollup(
    bom_rows: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One BOM row per part code; drop synthesized detail rows already on a GA line."""
    est_codes = {_est_code(e) for e in part_estimates if _est_code(e)}
    shadowed = codes_shadowed_by_parent_bom(bom_rows, est_codes)
    by_code: Dict[str, Dict[str, Any]] = {}
    for row in bom_rows:
        code = _row_code(row)
        if not code:
            continue
        if row.get("source") == "folder_job_synthesized" and code in shadowed:
            continue
        pri = _BOM_SOURCE_PRIORITY.get(str(row.get("source") or ""), 5)
        prev = by_code.get(code)
        if prev is None or pri < _BOM_SOURCE_PRIORITY.get(str(prev.get("source") or ""), 5):
            by_code[code] = row
    return list(by_code.values())


def dedupe_weldment_parent_rows(bom_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop weldment parent (-101) when its detail children are also BOM lines."""
    codes = {_row_code(r) for r in bom_rows if _row_code(r)}
    drop: set = set()
    for code in codes:
        if not _WELDMENT_PARENT_RE.search(code):
            continue
        prefix = _WELDMENT_PARENT_RE.sub("", code)
        children = [
            c
            for c in codes
            if c.startswith(prefix + "-") and c != code and not _WELDMENT_PARENT_RE.search(c)
        ]
        if children:
            drop.add(code)
    return [r for r in bom_rows if _row_code(r) not in drop]


def synthesize_folder_job_bom_rows(
    summary: Dict[str, Any],
    part_estimates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build a job-level bay BOM when the folder has no top-level 1282-GA PDF."""
    rows = [dict(r) for r in (summary.get("document_analysis") or {}).get("bom_rows") or []]
    try:
        from part_identity import inject_missing_bay_rows

        rows = inject_missing_bay_rows(rows, summary)
    except Exception:
        pass
    existing = {_row_code(r) for r in rows if _row_code(r)}

    for est in part_estimates:
        code = _est_code(est)
        if not code or code in existing or code in _JUNK_ESTIMATE_CODES:
            continue
        try:
            from part_identity import dxf_alias_target

            alias = dxf_alias_target(code)
            if alias and _norm_code(alias) in existing:
                continue
        except Exception:
            pass
        if not code[0].isdigit():
            continue
        desc = str(est.get("description") or code)
        if classify_bom_line(code, desc) == "catalogue":
            continue
        rows.append(
            {
                "part_number": code,
                "description": desc,
                "quantity": est.get("quantity") or 1,
                "source": "folder_job_synthesized",
            }
        )
        existing.add(code)

    for row in extract_catalogue_bom_rows_from_pages(summary):
        code = _row_code(row)
        if code and code not in existing:
            rows.append(row)
            existing.add(code)

    rows = dedupe_weldment_parent_rows(rows)
    return dedupe_bom_rows_for_bay_rollup(rows, part_estimates)


def job_has_costing_root(bom_rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> bool:
    for row in bom_rows:
        pn = str(row.get("part_number") or "").upper()
        if re.search(r"\b1282\b", pn) and "-GA" in pn:
            return True
    codes = {_row_code(r) for r in bom_rows}
    return "1449-01C" in codes and "1450-01C" in codes


# ── Rollup ───────────────────────────────────────────────────────────────────

def build_bay_estimate(
    bom_rows: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
    *,
    order_quantity: int = 1,
    catalogue_pricer: Optional[Callable[[str, str], Optional[Dict[str, Any]]]] = None,
    packaging_lines: Optional[List[Dict[str, Any]]] = None,
    data_sufficiency_floor: float = 0.60,
    allow_ga_provisional: bool = True,
) -> Dict[str, Any]:
    order_qty = max(1, int(order_quantity or 1))
    bom_rows = dedupe_bom_rows_for_bay_rollup(bom_rows, part_estimates)

    est_by_code: Dict[str, Dict[str, Any]] = {}
    for e in part_estimates:
        c = _est_code(e)
        if c:
            est_by_code.setdefault(c, e)

    claimed_exact: set = set()
    for row in bom_rows:
        c = _row_code(row)
        if c and classify_bom_line(c, _row_description(row)) != "catalogue" and c in est_by_code:
            claimed_exact.add(c)

    bound_detail_codes: set = set()
    shadowed_details = codes_shadowed_by_parent_bom(bom_rows, est_by_code.keys())
    lines: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []

    def _flag(severity: str, code: str, detail: str):
        flags.append({"severity": severity, "line": code, "detail": detail})

    def _apply_cost(
        line: Dict[str, Any],
        *,
        uc: float,
        qty: float,
        source: str,
        provisional: bool,
        extra: Optional[Dict[str, Any]] = None,
    ):
        line.update(
            unit_cost_gbp=round(uc, 2),
            line_cost_gbp=round(uc * qty, 2),
            cost_source=source,
            costed=True,
            cost_confidence=_line_confidence(provisional=provisional),
            provisional=provisional,
        )
        if extra:
            line.update(extra)

    for row in bom_rows:
        code = _row_code(row)
        desc = _row_description(row)
        qty = _row_qty(row)
        if not code:
            continue
        if code in shadowed_details:
            continue
        kind = classify_bom_line(code, desc)

        line: Dict[str, Any] = {
            "code": code,
            "description": desc,
            "qty_per_bay": qty,
            "kind": kind,
            "unit_cost_gbp": None,
            "line_cost_gbp": 0.0,
            "cost_source": None,
            "costed": False,
            "cost_confidence": None,
            "provisional": False,
        }

        if kind == "consumable":
            _flag(
                "info",
                code,
                f"'{desc}' is a per-part consumable (powder) — already costed in the part "
                f"estimate; not re-added as a BOM line",
            )
            line["cost_source"] = "consumable_per_part"
            lines.append(line)
            continue

        if kind == "catalogue":
            priced = None
            if catalogue_pricer:
                priced = catalogue_pricer(code, desc)
                if not (priced and priced.get("unit_cost_gbp") is not None):
                    try:
                        from part_identity import catalogue_search_descriptions

                        for variant in catalogue_search_descriptions(code, desc)[1:]:
                            priced = catalogue_pricer(code, variant)
                            if priced and priced.get("unit_cost_gbp") is not None:
                                break
                    except Exception:
                        pass
            if priced and priced.get("unit_cost_gbp") is not None:
                uc = float(priced["unit_cost_gbp"])
                _apply_cost(
                    line,
                    uc=uc,
                    qty=qty,
                    source=priced.get("source") or "catalogue",
                    provisional=False,
                    extra={"matched_part_code": priced.get("matched_part_code")},
                )
            else:
                reason = (priced or {}).get("reason") or "no parts-DB match"
                _flag("warning", code, f"catalogue token '{desc}' not priced ({reason}) — price manually")
                line["cost_source"] = (priced or {}).get("source") or "catalogue_unpriced"

        else:
            try:
                from part_identity import resolve_estimate_code

                resolved = resolve_estimate_code(code, desc, est_by_code.keys())
            except Exception:
                resolved = None
            # Multi-child GA: roll up all shadowed detail estimates on the parent line.
            if resolved and (_ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly"):
                if len(_assembly_child_codes(code, est_by_code.keys())) > 1:
                    resolved = None
            if resolved and resolved in est_by_code:
                code = resolved
                line["code"] = code

            if code in est_by_code:
                uc = _est_unit_cost(est_by_code[code])
                if uc is not None and uc > 0:
                    prov = _est_is_provisional(est_by_code[code])
                    _apply_cost(line, uc=uc, qty=qty, source="fab_estimate", provisional=prov)
                    if prov:
                        _flag(
                            "warning",
                            code,
                            f"fab estimate for '{desc}' is provisional (inferred geometry / insufficient data)",
                        )
                    bound_detail_codes.add(code)
                elif uc is not None and uc <= 0:
                    _flag("warning", code, "matched fab estimate is £0 — price manually")
                else:
                    _flag("warning", code, "matched fab estimate has no unit cost — price manually")

            else:
                base = _assembly_base(code)
                prefix = _numeric_prefix(base or code)

                def _is_child(c: str) -> bool:
                    if c in claimed_exact or c in bound_detail_codes:
                        return False
                    if c == code:
                        return False
                    if c.startswith(code + "-") or c == base or c.startswith(base + "-"):
                        return True
                    if prefix and c.startswith(prefix + "-"):
                        return True
                    return False

                children = [(c, e) for c, e in est_by_code.items() if _is_child(c)]
                if children:
                    sub = 0.0
                    ok = True
                    any_prov = False
                    child_codes: List[str] = []
                    for c, ch in children:
                        cu = _est_unit_cost(ch)
                        if cu is None:
                            ok = False
                            continue
                        sub += cu
                        bound_detail_codes.add(c)
                        child_codes.append(c)
                        if _est_is_provisional(ch):
                            any_prov = True
                    if ok and sub > 0:
                        _apply_cost(
                            line,
                            uc=sub,
                            qty=qty,
                            source=f"assembly_of_{len(children)}_parts",
                            provisional=any_prov,
                            extra={"child_part_codes": child_codes, "kind": "assembly"},
                        )
                        if any_prov:
                            _flag(
                                "warning",
                                code,
                                f"assembly {base}: rolled up from {len(children)} part(s) with provisional geometry",
                            )
                    else:
                        _flag(
                            "warning",
                            code,
                            f"assembly {base}: {len(children)} detail part(s) but some uncosted — review",
                        )
                elif allow_ga_provisional and (_ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly"):
                    prov = provisional_cost_from_ga_bom(desc)
                    if prov and prov.get("unit_cost_gbp") is not None:
                        _apply_cost(
                            line,
                            uc=float(prov["unit_cost_gbp"]),
                            qty=qty,
                            source=prov.get("source") or "ga_bom_provisional",
                            provisional=True,
                            extra={
                                "kind": "assembly",
                                "inference_basis": prov.get("inference_basis"),
                                "blank_mm": prov.get("blank_mm"),
                            },
                        )
                        _flag("warning", code, prov.get("note") or "GA BOM provisional estimate — verify")
                    else:
                        _flag(
                            "error",
                            code,
                            f"assembly line '{desc}' has no costed detail parts and no GA description "
                            f"fallback — missing GA/detail set; price manually",
                        )
                        line.update(kind="assembly", cost_source="placeholder_no_detail")
                elif _ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly":
                    _flag(
                        "error",
                        code,
                        f"assembly line '{desc}' has no costed detail parts in scope — "
                        f"missing GA/detail set; price manually",
                    )
                    line.update(kind="assembly", cost_source="placeholder_no_detail")
                else:
                    _flag(
                        "error",
                        code,
                        f"BOM line '{desc}' has no cost basis (no estimate, no catalogue match) — price manually",
                    )
                    line["cost_source"] = "no_cost_basis"

        lines.append(line)

    for pl in packaging_lines or []:
        uc = float(pl.get("unit_cost_gbp") or 0.0)
        qty = float(pl.get("qty_per_bay") or 1.0)
        lines.append(
            {
                "code": pl.get("code") or "PACKAGING",
                "description": pl.get("description") or "Packaging",
                "qty_per_bay": qty,
                "kind": "template",
                "unit_cost_gbp": round(uc, 2),
                "line_cost_gbp": round(uc * qty, 2),
                "cost_source": "template",
                "costed": True,
                "cost_confidence": "high",
                "provisional": False,
            }
        )

    costed_lines = [ln for ln in lines if ln["costed"]]
    confident_lines = [ln for ln in costed_lines if ln.get("cost_confidence") == "high"]
    provisional_lines = [ln for ln in costed_lines if ln.get("provisional")]

    bay_unit_total = round(sum(ln["line_cost_gbp"] for ln in costed_lines), 2)
    bay_confident_total = round(sum(ln["line_cost_gbp"] for ln in confident_lines), 2)

    _excluded_kinds = {"template", "consumable"}
    n_lines = len([ln for ln in lines if ln["kind"] not in _excluded_kinds])
    n_uncosted = len([ln for ln in lines if ln["kind"] not in _excluded_kinds and not ln["costed"]])
    coverage = (n_lines - n_uncosted) / n_lines if n_lines else 0.0
    has_provisional = bool(provisional_lines)
    sufficient = (
        coverage >= data_sufficiency_floor
        and n_uncosted == 0
        and not has_provisional
    )

    return {
        "schema": "bay_estimate.v1",
        "order_quantity": order_qty,
        "bay_unit_total_gbp": bay_confident_total if sufficient else None,
        "bay_unit_total_provisional_gbp": bay_unit_total,
        "bay_unit_total_confident_gbp": bay_confident_total,
        "headline_suppressed": not sufficient,
        "line_coverage": round(coverage, 3),
        "uncosted_lines": n_uncosted,
        "provisional_lines": len(provisional_lines),
        "bom_line_count": len(lines),
        "lines": lines,
        "flags": flags,
    }


def make_system_cost_pricer(resolve_part_system_cost, *, reject_above_gbp: float = 750.0):
    """Adapt _resolve_part_system_cost into a bay catalogue_pricer with £750 guard."""
    def pricer(code: str, desc: str):
        try:
            from part_identity import catalogue_search_descriptions

            desc_variants = catalogue_search_descriptions(code, desc)
        except Exception:
            desc_variants = [desc]
        for variant in desc_variants:
            part = {"part_number": code, "description": variant}
            try:
                res = resolve_part_system_cost(part) or {}
            except Exception as e:
                return {"unit_cost_gbp": None, "source": "system_cost_error", "reason": f"pricer error: {e}"}
            uc = res.get("applied_unit_cost")
            matched = res.get("matched_part_code")
            if uc is None:
                continue
            try:
                uc = float(uc)
            except (TypeError, ValueError):
                continue
            if uc <= 0 or uc > reject_above_gbp:
                continue
            return {
                "unit_cost_gbp": uc,
                "source": "system_cost",
                "matched_part_code": matched,
                "confidence": 0.9,
            }
        return {"unit_cost_gbp": None, "source": "system_cost_no_match", "reason": "no parts-DB match"}

    return pricer
