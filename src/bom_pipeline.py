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

import os
import re
from typing import Any, Dict, List, Optional, Sequence


def dual_path_enabled() -> bool:
    """Whether the reconciled two-reader BOM is the job's BOM. Default: yes.

    It was built behind SDI_DUALPATH_BOM, default OFF, so that turning it on could not
    change a baseline. The consequence was that no live run ever read a BOM table: the
    rows reaching the estimate came from regexes over pdfplumber's text flow, which
    scrambles ruled CAD tables and needs per-drawing string repairs to survive — the
    opposite of a rule that carries to the next job. A drawing states its own bill of
    materials; reading it is not an experiment.

    SDI_DUALPATH_BOM=0 still forces the old single-reader path for a like-for-like
    comparison. The check lives HERE, once, because it previously existed as two
    independent env reads in file_scan and either could have gone stale on its own.
    """
    return os.getenv("SDI_DUALPATH_BOM", "1").strip().lower() not in {"0", "false", "no", "off"}


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


# EVERY DRAWING HAS A BORDER, AND IT IS NUMBERED.
#
# M&S 2085's sheet is gridded 1-20 across and A-I down. The deterministic table reader
# swallowed "...14 15 16 17 18 19 20" sitting immediately before the "ITEM NO." header and
# emitted part_number "1415", description "16 17 18 19", quantity 20. It was priced by an AI
# market estimate at GBP 10.54 each: GBP 219.21 of a GBP 273.98 unit cost, 80% of the job,
# from the picture frame.
#
# The vision pass refused to corroborate it and the row was flagged "A-only ... review". The
# flag was right and nothing acted on it. This does: a description with no letters in it is
# not a description, and a part number that is only digits with no separator is not one of
# SDI's or a customer's. Neither test alone is safe — a real row can be "1415" if the
# customer numbers that way, and "M6 x 20" is a real description — so both must hold.
_ALPHA = None


def is_drawing_furniture(code: str, description: str) -> bool:
    """True when a BOM row is the drawing's own border grid rather than a part.

    Deliberately narrow. Dropping a real BOM line is far worse than costing a phantom one:
    a phantom is visible in the total and gets challenged, a missing part is silent.
    """
    import re as _re
    desc = str(description or "").strip()
    code_s = str(code or "").strip()
    if not desc or not code_s:
        return False
    # A description with any letter in it is somebody's words. Only pure digits, spaces and
    # punctuation can be grid furniture.
    if _re.search(r"[A-Za-z]", desc):
        return False
    # And the code must itself be featureless: digits only, no separator of any kind. Real
    # numbering here always carries one (2085-01, 12120-01-01M, BI-KNURLEDKNOB, THUM620).
    if not _re.fullmatch(r"\d+", code_s):
        return False
    return True


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
    findings_extra: List[Dict[str, Any]] = []
    # Parents, not pages. A page is one sheet; a parent is one drawing's bill of
    # materials, which is the thing an estimate is built from. Reading pages here gave a
    # parent whose list spans two sheets two half-BOMs, and a fixings table repeated on
    # a detail sheet double the fixings. Falls back to pages so an older reconcile
    # result — or a caller that builds one by hand — still flattens.
    _groups = result.get("parents")
    if _groups is None:
        _groups = result.get("pages", [])
    for pg in _groups:
        parent = pg.get("label")
        _parent_known = pg.get("parent_known", True)
        for r in pg.get("rows", []):
            code = _norm_code(r.get("part_number") or r.get("part_ref") or "")
            desc = str(r.get("description") or "").strip()
            try:
                qty = int(r.get("quantity"))
            except (TypeError, ValueError):
                qty = 1
            if is_drawing_furniture(code, desc):
                findings_extra.append({
                    "code": "bom_row_is_drawing_furniture",
                    "detail": f"dropped BOM row part='{code}' desc='{desc}' qty={qty} — "
                              f"a description with no letters in it is not a part name; this "
                              f"is the drawing's border grid, read as a BOM line",
                    "page": parent,
                })
                continue
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
                # False when the sheet's title block named no drawing and this group is a
                # file+page placeholder. It groups the rows correctly and it is not a
                # drawing number, so nothing downstream may hang a hierarchy on it.
                "bom_parent_known": _parent_known,
                # Which sheet the row was read off, and any others that restated it.
                "bom_sheet": r.get("sheet"),
                "bom_also_on_sheets": list(r.get("also_on_sheets") or []) or None,
            })
    # A reader that did not run is the only failure this module cannot see in its output:
    # the rows simply are not there, and a job read by one path looks exactly like a job
    # both paths agreed was small. Promote every unread scope to a finding so the absence
    # is stated rather than inferred from a count nobody compares.
    for u in result.get("unread", []) or []:
        _scope = u.get("scope")
        _where = u.get("pdf") or "this job"
        if u.get("page") is not None:
            _where = f"{_where} page {int(u['page']) + 1}"
        findings_extra.append({
            "code": "bom_reader_did_not_run",
            "detail": (
                f"{'deterministic' if u.get('path') == 'A' else 'vision'} BOM reader did not "
                f"read {_where}: {u.get('detail')}. Rows it would have contributed are not "
                f"missing from the BOM — they are unknown, and no row on this "
                f"{'job' if _scope == 'job' else _scope} carries two-reader corroboration."
            ),
            "page": u.get("pdf") or None,
            "severity": "blocking" if _scope == "job" else "review",
        })
    return {
        "rows": flat,
        "findings": list(result.get("findings", [])) + findings_extra,
        "unread": list(result.get("unread", []) or []),
        # {'paid','cached','skipped'} vision calls. Reported so the cost of a run is a
        # number an estimator can see rather than something inferred from the bill.
        "vision_calls": dict(result.get("vision_calls") or {}),
        "counts": result.get("counts", {}),
        "pdf_paths": result.get("pdf_paths", []),
        # a_count/b_count = how many BOM tables each reader found across the job.
        # Surfaced so a caller can tell an EMPTY dual-path result apart: a_count==0
        # means the deterministic reader found no table (reader bug), b_count==0 means
        # Grok vision was unavailable/uncached (offline — Path A alone still suffices).
        "a_count": result.get("a_count", 0),
        "b_count": result.get("b_count", 0),
    }
