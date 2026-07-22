"""
bom_pipeline.py — bridge from the proven dual-path BOM reconciler (merge_boms) into
the live estimator pipeline.

reconciled_bom_rows_for_job() resolves a job's PDFs, runs Path A (deterministic
pdfplumber) + Path B (Grok vision) reconciliation via merge_boms.reconcile_job, and
returns a FLAT list of {part_number, description, quantity} rows — the exact shape
build_document_writeup consumes. Reconciliation provenance (source/confidence/flag/
parent) rides along as extra keys; build_document_writeup ignores them, the drawing-
quality report uses them.

Vision-only codes (a row carrying part_ref with no canonical part_number, e.g. the
1282 kick-plate 1453-GA-C that Path A left blank) are promoted into part_number so
the consumer's part-number-keyed logic (Fix A/B/C dedup + backfill) sees them.
Nothing here calls Grok directly — it delegates to the proven merge_boms functions.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence


# A "formal code" is normalised (whitespace squashed, upper-cased, hyphens cleaned):
#   - SDI drawing reference: starts with a digit  (1453-GA-C, 1450 - GA, 3886-02-)
#   - letter-prefix catalogue code ENDING at its digits  (FIXING 236, VINYL76)
# Anything else — a word/unit description such as 'ELECTRICS 50cm' — is left with its
# internal spacing intact. This matters: the estimator's bought-in reconciler folds
# described commodities (loom, foam tape) by FUZZY TOKEN SUBSET, and squashing
# '50cm' into the code destroys the standalone 50/cm tokens its match needs — which
# duplicated the loom on 1282 (ELECTRICS50CM no longer folded into BI-50CMLOOM).
# Formal codes (FIXING236) still squash because they dedup by EXACT code, not tokens.
_SDI_CODE_RE = re.compile(r"^\d")
_LETTER_CODE_RE = re.compile(r"^[A-Za-z]+\s*\d+$")


def _norm_code(raw: Any) -> str:
    """Canonicalise a BOM code, but ONLY for formal codes (SDI refs and letter-prefix
    catalogue codes). Descriptions keep their spacing so fuzzy bought-in reconciliation
    still works. Idempotent on clean Path-A codes; repairs vision variants like
    '3886-GA-' -> '3886-GA', '1450 - GA' -> '1450-GA', 'FIXING 236' -> 'FIXING236';
    leaves 'ELECTRICS 50cm' untouched."""
    s = str(raw or "").strip()
    if _SDI_CODE_RE.match(s) or _LETTER_CODE_RE.match(s):
        s = re.sub(r"\s+", "", s).upper()
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-")
    return s


def reconciled_bom_rows_for_job(
    *,
    folder: Optional[Any] = None,
    pdfs: Optional[Sequence[Any]] = None,
    **opts: Any,
) -> Dict[str, Any]:
    """Run the dual-path reconcile for a job and flatten to bom_rows.

    Exactly one of ``folder`` (a job folder — all PDFs discovered via the
    case-insensitive DEDUPED merge_boms.find_pdfs) or ``pdfs`` (an explicit list)
    should be given. ``opts`` are forwarded to reconcile_job (dpi, max_side, model,
    cache_dir, no_cache, refresh, force_llm, refresh_file).

    Returns {'rows': [...], 'findings': [...], 'counts': {...}, 'pdf_paths': [...]}.
    On no PDFs or an import failure the caller keeps its existing rows (empty 'rows').
    Deliberately does NOT dedup rows: the same code legitimately recurs across parent
    BOMs, and the downstream consumer (Fix B/C dedup) + bom_tree qty resolution apply
    their own existing logic — matching how the pipeline treats bom_rows today.
    """
    from merge_boms import find_pdfs, reconcile_job

    if folder is not None:
        pdf_paths = find_pdfs(str(folder))
    elif pdfs:
        pdf_paths = [str(p) for p in pdfs if p]
    else:
        pdf_paths = []
    if not pdf_paths:
        return {"rows": [], "findings": [], "counts": {}, "pdf_paths": [],
                "a_count": 0, "b_count": 0}

    result = reconcile_job(pdf_paths, verbose=False, **opts)

    flat: List[Dict[str, Any]] = []
    for pg in result.get("pages", []):
        parent = pg.get("label")
        for r in pg.get("rows", []):
            code = _norm_code(r.get("part_number") or r.get("part_ref") or "")
            desc = str(r.get("description") or "").strip()
            try:
                qty = int(r.get("quantity"))
            except (TypeError, ValueError):
                qty = 1
            flat.append({
                # --- the three keys build_document_writeup reads ---
                "part_number": code,
                "description": desc,
                "quantity": qty,
                # --- source_pdf: the parent-BOM label, so bom_tree.resolve_effective_
                #     quantities can group our rows by drawing and cascade the parent GA
                #     multiplier into the leaves (e.g. 1448-01 x1 under 1448-GA x2 -> 2).
                #     bom_tree keys its whole tree on source_pdf; without this our rows
                #     are invisible to it and leaves stay at their per-sub-assembly qty.
                "source_pdf": parent,
                # --- provenance: ignored by the consumer, used by the report ---
                "bom_source": r.get("source"),
                "bom_confidence": r.get("confidence"),
                "bom_flag": r.get("flag"),
                "bom_parent": parent,
            })
    return {
        "rows": flat,
        "findings": result.get("findings", []),
        "counts": result.get("counts", {}),
        "pdf_paths": result.get("pdf_paths", []),
        # a_count/b_count = how many BOM tables each reader found across the job.
        # Surfaced so a caller can tell an EMPTY dual-path result apart: a_count==0
        # means the deterministic reader found no table (reader bug), b_count==0 means
        # Grok vision was unavailable/uncached (offline — Path A alone still suffices).
        "a_count": result.get("a_count", 0),
        "b_count": result.get("b_count", 0),
    }
