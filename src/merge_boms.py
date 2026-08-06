#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
merge_boms.py — DUAL-PATH BOM RECONCILIATION (the architecture, standalone).

Runs BOTH BOM readers on a job and reconciles them into ONE BOM with provenance
+ drawing-quality findings, per the locked rules:

  PATH A (deterministic, _bom_words_reader.read_bom_from_page): the BASE.
  PATH B (Grok vision, _bom_vision_reader, cached): the COVERAGE net.

  Reconciliation, per (parent, item):
    both agree (code + qty)     -> A's row,  source=BOTH,        conf=HIGH, no flag
    both differ (code or qty)   -> B's row,  source=B_OVERRIDE,  conf=LOW,  flag: override
                                    + "possible drawing inconsistency" (Grok wins, your Q1)
    A only (Grok didn't find)   -> A's row,  source=A_ONLY,      conf=MED,  flag: A-only
    B only (A didn't find)      -> B's row,  source=B_RECOVERED, conf=MED,  flag: LLM-recovered
    whole parent in one path    -> emit rows, flagged which path

Guarantee: NO SILENT MISS — every item found by either path is emitted; anything
found by only one path, or where the two disagree, is FLAGGED for review. Grok
overlays what A didn't find (your words). The cache means Grok is free on re-runs.

Alignment notes (both readers' real schemas):
  - Rows share item_number / part_ref / description / quantity(int). No translation.
  - Parents are derived DIFFERENTLY: Path A's title-block regex is tuned for the
    12120-01-XXX format, so on 1282 it may yield parent=None. Path B (Grok) reads
    the title-block verbatim ('1282 - GA'). So we group by a normalised parent key,
    and when parents don't line up we JOIN ON (pdf_name, page_index) — both readers
    processed the same physical page, so file+page is a reliable join.

Run (from C:\ClaudeVision\src so both readers + cache import):
  C:\ClaudeVision\.venv\Scripts\python.exe merge_boms.py --pdf-dir "<job folder>"
  flags: --force-llm / --refresh-file <substr> / --no-cache / --dpi / --max-side / --model
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# This module started life as a standalone script and exited the process when a
# reader would not import. It is now imported by the live pipeline, where that
# call would take the whole estimate down over a missing optional dependency —
# so an import failure is recorded and reported instead. main() still refuses to
# run without both readers; the difference is that only main() may end the process.
PATH_A_IMPORT_ERROR: Optional[str] = None
PATH_B_IMPORT_ERROR: Optional[str] = None

# ---- import Path A (deterministic reader) ----
try:
    import _bom_words_reader as pathA
except Exception as exc:  # pragma: no cover - environment-dependent
    pathA = None  # type: ignore[assignment]
    PATH_A_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# ---- import Path B (vision reader + cache) ----
try:
    import _bom_vision_reader as pathB
except Exception as exc:  # pragma: no cover - environment-dependent
    pathB = None  # type: ignore[assignment]
    PATH_B_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Shared normalisation (bare code = uppercase, all separators stripped), reused
# from Path B so A and B codes compare identically.
# ---------------------------------------------------------------------------
# '3886-GA-' / '1450 - GA' / '1455-C GA' -> '3886GA' / '1450GA' / '1455CGA'.
# Taken from part_code_conventions, not from Path B: reconciliation must still be able to
# compare codes on a machine where the vision reader will not import.
from part_code_conventions import bare_code as _bare


def _parent_key(parent: Optional[str], pdf_name: str, page_index: int) -> str:
    """Group key for aligning A and B. Prefer a normalised parent code; if absent
    (Path A can yield None on 1282), fall back to the physical page identity so the
    two readers' views of the SAME page still align."""
    if parent and _bare(parent):
        return "P:" + _bare(parent)
    return f"F:{pdf_name}#{page_index}"


# A page can be keyed by parent OR by file+page. To be robust we index B by BOTH
# so A can find B's rows whichever key A ends up with.
def _index_by_keys(boms: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for bom in boms:
        pkey = _parent_key(bom.get("parent"), bom.get("pdf_name", ""), bom.get("page_index", -1))
        fkey = f"F:{bom.get('pdf_name','')}#{bom.get('page_index',-1)}"
        idx[pkey] = bom
        idx[fkey] = bom  # also reachable by file+page
    return idx


def _rows_by_item(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(r["item_number"]): r for r in rows}


def reconcile_page(a_bom: Optional[Dict[str, Any]], b_bom: Optional[Dict[str, Any]],
                   parent_label: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Reconcile one parent's A-rows and B-rows. Returns (merged_rows, findings)."""
    findings: List[str] = []
    a_rows = (a_bom or {}).get("rows", [])
    b_rows = (b_bom or {}).get("rows", [])
    a_by = _rows_by_item(a_rows)
    b_by = _rows_by_item(b_rows)
    all_items = sorted(set(a_by) | set(b_by), key=lambda s: (len(s), s))

    merged: List[Dict[str, Any]] = []
    for item in all_items:
        a = a_by.get(item)
        b = b_by.get(item)

        if a and b:
            a_code, b_code = _bare(a.get("part_ref", "")), _bare(b.get("part_ref", ""))
            a_qty, b_qty = int(a["quantity"]), int(b["quantity"])
            code_agree = (a_code == b_code) or (a_code == "" and b_code == "") \
                or (a_code and b_code and (a_code in b_code or b_code in a_code))
            qty_agree = (a_qty == b_qty)
            if code_agree and qty_agree:
                row = dict(a); row["source"] = "BOTH"; row["confidence"] = "HIGH"; row["flag"] = ""
                merged.append(row)
            else:
                # conflict -> Grok wins (your Q1), flag override + drawing-inconsistency
                row = dict(b)
                row["source"] = "B_OVERRIDE"; row["confidence"] = "LOW"
                diff = []
                if not code_agree:
                    diff.append(f"code A='{a.get('part_ref','')}' vs B='{b.get('part_ref','')}'")
                if not qty_agree:
                    diff.append(f"qty A={a_qty} vs B={b_qty}")
                row["flag"] = "OVERRIDE (vision wins) — possible drawing inconsistency: " + "; ".join(diff)
                merged.append(row)
                findings.append(f"[{parent_label}] item {item}: {row['flag']}")
        elif a and not b:
            row = dict(a); row["source"] = "A_ONLY"; row["confidence"] = "MED"
            row["flag"] = "A-only (vision did not corroborate) — review"
            merged.append(row)
            findings.append(f"[{parent_label}] item {item}: found by deterministic reader only "
                            f"(code '{a.get('part_ref','')}', qty {a['quantity']}) — vision missed it")
        elif b and not a:
            row = dict(b); row["source"] = "B_RECOVERED"; row["confidence"] = "MED"
            row["flag"] = "LLM-recovered (deterministic reader missed it) — review"
            merged.append(row)
            findings.append(f"[{parent_label}] item {item}: RECOVERED by vision "
                            f"(code '{b.get('part_ref','')}', qty {b['quantity']}) — deterministic reader missed it")
    return merged, findings


# ---------------------------------------------------------------------------
# Drawing-quality signals from the codes themselves (format inconsistencies),
# independent of A-vs-B. Captured now for the future report section.
# ---------------------------------------------------------------------------
def code_quality_findings(parent_label: str, rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    codes = [r.get("part_ref", "") for r in rows if r.get("part_ref")]
    for c in codes:
        if re.search(r"\s-\s|\s-|-\s", c):
            out.append(f"[{parent_label}] code '{c}': stray space around hyphen")
        if c.endswith("-"):
            out.append(f"[{parent_label}] code '{c}': trailing hyphen")
    # inconsistent trailing-hyphen within one table (some have it, some don't)
    fam: Dict[str, List[str]] = {}
    for c in codes:
        stem = re.sub(r"[-\s]+$", "", c)
        stem = re.sub(r"-\d+-?$", "", stem)  # rough family stem (e.g. 3886)
        m = re.match(r"^(\d{3,})", c)
        if m:
            fam.setdefault(m.group(1), []).append(c)
    for stem, members in fam.items():
        has_tr = [c for c in members if c.endswith("-")]
        no_tr = [c for c in members if not c.endswith("-")]
        if has_tr and no_tr:
            out.append(f"[{parent_label}] family {stem}: INCONSISTENT trailing hyphens "
                       f"(e.g. {no_tr[0]} vs {has_tr[0]}) — standardise")
    return out


# ---------------------------------------------------------------------------
# Run both readers over a job.
# ---------------------------------------------------------------------------
# A page neither reader could look at is a page whose BOM cannot be missing-or-present:
# it is simply unknown, and that is the one state this module must never report as clean.
# Both runners therefore append to `unread`, and reconcile_job carries those out to the
# caller as findings. Prints alone were how a whole job ran vision-blind in silence.
def run_path_a(pdf_paths: List[str], unread: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    import pdfplumber
    out: List[Dict[str, Any]] = []
    if pathA is None:
        if unread is not None:
            unread.append({"path": "A", "scope": "job", "pdf": "", "page": None,
                           "detail": f"deterministic BOM reader unavailable ({PATH_A_IMPORT_ERROR})"})
        return out
    for p in pdf_paths:
        try:
            with pdfplumber.open(p) as pdf:
                for pi, page in enumerate(pdf.pages):
                    bom = pathA.read_bom_from_page(page)
                    if bom:
                        bom["page_index"] = pi
                        bom["pdf_name"] = os.path.basename(p)
                        out.append(bom)
        except Exception as exc:
            print(f"  [Path A skip] {os.path.basename(p)}: {exc}")
            if unread is not None:
                unread.append({"path": "A", "scope": "file", "pdf": os.path.basename(p), "page": None,
                               "detail": f"{type(exc).__name__}: {exc}"})
    return out


def run_path_b(pdf_paths: List[str], args, unread: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if pathB is None:
        if unread is not None:
            unread.append({"path": "B", "scope": "job", "pdf": "", "page": None,
                           "detail": f"vision BOM reader unavailable ({PATH_B_IMPORT_ERROR})"})
        return out
    force_all = args.refresh or args.force_llm
    for p in pdf_paths:
        this_refresh = force_all or (
            args.refresh_file is not None and args.refresh_file.lower() in os.path.basename(p).lower()
        )
        try:
            n = pathB.count_pages(p)
        except Exception as exc:
            print(f"  [Path B skip] {os.path.basename(p)}: {exc}")
            if unread is not None:
                unread.append({"path": "B", "scope": "file", "pdf": os.path.basename(p), "page": None,
                               "detail": f"{type(exc).__name__}: {exc}"})
            continue
        for pi in range(n):
            try:
                png = pathB.render_page_to_png(p, pi, dpi=args.dpi, max_side=args.max_side)
                res = pathB.get_vision_bom_cached(
                    png, model=args.model, pdf_name=os.path.basename(p), page_index=pi,
                    cache_dir=args.cache_dir, use_cache=not args.no_cache, refresh=this_refresh,
                )
            except Exception as exc:
                print(f"  [Path B error] {os.path.basename(p)} p{pi}: {exc}")
                if unread is not None:
                    unread.append({"path": "B", "scope": "page", "pdf": os.path.basename(p), "page": pi,
                                   "detail": f"{type(exc).__name__}: {exc}"})
                continue
            parsed = res["parsed"]
            if parsed and parsed.get("rows"):
                parsed["page_index"] = pi
                parsed["pdf_name"] = os.path.basename(p)
                out.append(parsed)
    return out


def find_pdfs(pdf_dir: str) -> List[str]:
    if pathB is not None:
        return pathB.find_pdfs(pdf_dir)  # reuse the deduped finder
    # Same contract as the deduped finder: case-insensitive, one entry per real file.
    # Finding the job's PDFs must not depend on the vision reader importing.
    seen: Dict[str, str] = {}
    for name in sorted(os.listdir(pdf_dir)):
        if name.lower().endswith(".pdf"):
            seen.setdefault(name.lower(), os.path.join(pdf_dir, name))
    return list(seen.values())


def reconcile_job(
    pdf_paths,
    *,
    dpi=300,
    max_side=2000,
    model=None,
    cache_dir=None,
    no_cache=False,
    refresh=False,
    force_llm=False,
    refresh_file=None,
    verbose=False,
):
    """Dual-path BOM reconcile for a set of PDFs (library entry point).

    Runs Path A (deterministic) + Path B (Grok vision, cached) exactly as main() did,
    pairs pages by file+page, reconciles each, and returns structured results:
        {'pages': [{'label','a_bom','b_bom','rows','findings'}, ...],
         'findings': [...], 'counts': {'both','recovered','override','a_only'},
         'pdf_paths': [...], 'a_count': int, 'b_count': int}
    No Grok logic lives here -- it delegates to run_path_a / run_path_b, so behaviour
    is identical to the previous inline main() (verified: standalone output unchanged).
    """
    if model is None:
        model = os.environ.get("XAI_VISION_MODEL", "grok-4.3")
    if cache_dir is None:
        cache_dir = pathB.DEFAULT_CACHE_DIR if pathB is not None else ""
    _args = argparse.Namespace(
        pdf=None, pdf_dir=None, dpi=dpi, max_side=max_side, model=model,
        cache_dir=cache_dir, no_cache=no_cache, refresh=refresh,
        force_llm=force_llm, refresh_file=refresh_file,
    )
    unread: List[Dict[str, Any]] = []
    if verbose:
        print("\nRunning Path A (deterministic extract_words)...")
    a_boms = run_path_a(pdf_paths, unread)
    if verbose:
        print(f"  Path A found {len(a_boms)} BOM table(s).")
        print("Running Path B (Grok vision, cached)...")
    b_boms = run_path_b(pdf_paths, _args, unread)
    if verbose:
        print(f"  Path B found {len(b_boms)} BOM table(s).")

    b_index = _index_by_keys(b_boms)
    a_index = _index_by_keys(a_boms)
    seen_fp = set()
    pages = []
    counts = {"both": 0, "recovered": 0, "override": 0, "a_only": 0}
    total_findings = []
    for bom in a_boms + b_boms:
        fp = f"{bom.get('pdf_name','')}#{bom.get('page_index',-1)}"
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        fkey = f"F:{fp}"
        a_bom = a_index.get(fkey)
        b_bom = b_index.get(fkey)
        label = (b_bom or {}).get("parent") or (a_bom or {}).get("parent") or fp
        merged, findings = reconcile_page(a_bom, b_bom, label)
        if not merged:
            continue
        page_findings = list(findings) + code_quality_findings(label, merged)
        total_findings.extend(page_findings)
        for r in merged:
            s = r["source"]
            if s == "BOTH":
                counts["both"] += 1
            elif s == "B_RECOVERED":
                counts["recovered"] += 1
            elif s == "B_OVERRIDE":
                counts["override"] += 1
            elif s == "A_ONLY":
                counts["a_only"] += 1
        pages.append({"label": label, "a_bom": a_bom, "b_bom": b_bom,
                      "rows": merged, "findings": page_findings})
    # A job where one path never ran is not a reconciled job — it is a single-reader read
    # wearing a reconciled job's shape, and every "BOTH ... HIGH confidence" it cannot
    # produce is a corroboration that silently did not happen. Say so out loud.
    if pdf_paths and not any(u.get("path") == "B" and u.get("scope") == "job" for u in unread):
        if not b_boms:
            unread.append({"path": "B", "scope": "job", "pdf": "", "page": None,
                           "detail": "vision reader returned no BOM table on any page of this job"})
    if pdf_paths and pathA is not None and not a_boms:
        unread.append({"path": "A", "scope": "job", "pdf": "", "page": None,
                       "detail": "deterministic reader found no BOM table on any page of this job"})
    return {
        "pages": pages, "findings": total_findings, "counts": counts,
        "pdf_paths": list(pdf_paths), "a_count": len(a_boms), "b_count": len(b_boms),
        "unread": unread,
    }


def main():
    # Only the command line may end the process. Run standalone, this tool exists to
    # compare two readers, so one missing reader makes it pointless and it should say so
    # loudly. Imported, the same condition is a degraded read the caller must be told
    # about — never a reason to take an estimate down.
    for _label, _mod, _err in (("A (_bom_words_reader)", pathA, PATH_A_IMPORT_ERROR),
                               ("B (_bom_vision_reader)", pathB, PATH_B_IMPORT_ERROR)):
        if _mod is None:
            print(f"Could not import Path {_label}: {_err}")
            print("Run this from the src/ directory, with the project's virtualenv active.")
            sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2000)
    ap.add_argument("--model", default=os.environ.get("XAI_VISION_MODEL", "grok-4.3"))
    ap.add_argument("--cache-dir", default=pathB.DEFAULT_CACHE_DIR)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--force-llm", action="store_true")
    ap.add_argument("--refresh-file", default=None)
    args = ap.parse_args()
    if args.pdf:
        pdf_paths = [args.pdf]
    elif args.pdf_dir:
        pdf_paths = find_pdfs(args.pdf_dir)
    else:
        print("Provide --pdf-dir or --pdf."); sys.exit(1)
    if not pdf_paths:
        print("No PDFs found."); sys.exit(1)
    print("=" * 82)
    print("DUAL-PATH BOM RECONCILIATION  (Path A deterministic + Path B vision)")
    print(f"Files: {len(pdf_paths)}   Model: {args.model}   DPI: {args.dpi}")
    print("=" * 82)
    result = reconcile_job(
        pdf_paths, dpi=args.dpi, max_side=args.max_side, model=args.model,
        cache_dir=args.cache_dir, no_cache=args.no_cache, refresh=args.refresh,
        force_llm=args.force_llm, refresh_file=args.refresh_file, verbose=True,
    )
    for pg in result["pages"]:
        label = pg["label"]; a_bom = pg["a_bom"]; b_bom = pg["b_bom"]; merged = pg["rows"]
        a_n = len((a_bom or {}).get("rows", []))
        b_n = len((b_bom or {}).get("rows", []))
        print("\n" + "#" * 82)
        print(f"PARENT: {label}    (Path A: {a_n} rows, Path B: {b_n} rows -> merged: {len(merged)})")
        print("#" * 82)
        for r in merged:
            src = r["source"]; conf = r["confidence"]
            code = r.get("part_number") or r.get("part_ref") or ""
            tag = {"BOTH": "", "B_RECOVERED": "  <= RECOVERED by vision",
                   "B_OVERRIDE": "  <= VISION OVERRIDE", "A_ONLY": "  <= A-only"}.get(src, "")
            print(f"  item {str(r['item_number']):>2} | {code:<16} | {r.get('description','')[:36]:<36} "
                  f"| qty {r['quantity']} | {src:<11} {conf}{tag}")
    print("\n" + "=" * 82)
    print("RECONCILIATION SUMMARY")
    print("=" * 82)
    c = result["counts"]
    print(f"  BOTH agree (high confidence):     {c['both']}")
    print(f"  RECOVERED by vision (A missed):   {c['recovered']}   <- coverage vision adds")
    print(f"  VISION OVERRIDE (conflict):       {c['override']}   <- Grok won, flagged")
    print(f"  A-only (vision missed):           {c['a_only']}")
    print()
    if result["findings"]:
        print("DRAWING-QUALITY & REVIEW FINDINGS (for the emailed report):")
        for f in result["findings"]:
            print(f"  - {f}")
    else:
        print("No review findings -- both paths agreed on everything, codes clean.")
    print("=" * 82)


if __name__ == "__main__":
    main()
