"""
Orchestrated drawing pipeline: full PDF scan (JSON + estimating) + BOM table extract,
merged with pipeline JSON fields, written to dbo.drawing_bom_items.

Modes
-----
1) Single PDF::

    python -u .\\src\\pipeline_bom_estimate_sql.py --pdf "C:\\...\\drawing.pdf"

2) Single PDF + BOM ``dwg_no`` / part references → find child PDFs under extra dirs (and seed folder)::

    python -u .\\src\\pipeline_bom_estimate_sql.py --pdf "C:\\...\\GA.pdf" ^
        --reference-search-dir "C:\\...\\details" --reference-search-dir "C:\\...\\other"

   Extracts BOM from the GA, collects drawing-number tokens from ``dwg_no`` / ``item_number``
   (default regex or ``--reference-regex``), then finds ``*.pdf`` under those folders whose
   **file names contain** that token (with exact-stem / prefix rules preferred). Logs
   ``[REFERENCES] AMBIGUOUS`` when several files tie at the same match tier. Use
   ``--reference-transitive`` to follow BOM references on children (BFS, ``--reference-max-depth``).

3) DWG index root (stem regex over filenames)::

    python -u .\\src\\pipeline_bom_estimate_sql.py --dwg-index-root "C:\\...\\job_folder"

Options: ``--dry-run``, ``--no-sql``, ``--replace-drawing``, ``--strip-pricing``.

DB: same env as ``extract_bom_to_sql`` (BOM_SQL_*).
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

# Ensure repo root and src/ are importable when launched as a script.
_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
for _d in (_REPO, _SRC):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import extract_bom_to_sql as bom_sql
from extract_bom_to_sql import (
    TABLE_NAME,
    _drawing_number_from_json,
    build_insert_row,
    execute_dynamic_insert,
    extract_bom_tables,
    extract_from_pipeline_json,
    get_db_connection,
    get_insert_column_names,
    get_text_column_lengths,
)
from file_scan import scan_file


# Fields merged from pipeline JSON rows onto PDF BOM rows (same keys as rich pipeline insert).
_JSON_OVERLAY_KEYS: Set[str] = {
    "material",
    "thickness_mm",
    "finish",
    "colour",
    "width_mm",
    "operations",
    "risk_flags",
    "process_notes",
    "page_roles",
    "pipeline_part_json",
    "source_json_path",
    "json_part_confidence",
    "routing_steps_json",
    "primary_operation",
    "estimated_route_time_min",
}

_DEFAULT_DWG_STEM_REGEX = r"(?i)^(\d{4,5}-\d{2}(?:-[A-Z0-9_]+)+|\d{4,5}-\d{2}-[A-Z0-9_]+)$"

# Drawing-style tokens inside BOM dwg_no / item_number (e.g. 9680-02-001, 12242-01-GA).
_REFERENCE_TOKEN_RE = re.compile(
    r"\b(\d{4,6}-(?:[A-Z0-9]+-)+[A-Z0-9]+|\d{4,6}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*)\b",
    re.IGNORECASE,
)


def _compile_reference_token_pattern(expr: Optional[str]) -> Pattern[str]:
    """Compile ``--reference-regex`` or return the default BOM drawing-number pattern."""
    if not expr or not str(expr).strip():
        return _REFERENCE_TOKEN_RE
    return re.compile(str(expr).strip(), re.IGNORECASE)


def _norm_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _overlay_match_keys(row: Dict[str, Any]) -> List[str]:
    """
    Prefer real identifiers over row-number style item numbers when merging BOM rows with pipeline rows.
    """
    keys: List[str] = []
    for raw in (row.get("dwg_no"), row.get("part_number"), row.get("item_number")):
        key = _norm_key(raw)
        if key and key not in keys:
            keys.append(key)
    return keys


def _revision_rank_from_path(pdf_path: Path) -> int:
    """
    Higher number means a later alphabetic revision. Missing revision sorts lowest.
    """
    name = pdf_path.name.upper()
    match = re.search(r"(?:^|[\s._()-])REV(?:ISION)?[\s._()-]*([A-Z])(?:$|[\s._()-])", name)
    if not match:
        return -1
    return ord(match.group(1)) - ord("A")


def _strip_estimate_pricing(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy with obvious GBP / unit cost fields removed from estimate_summary."""
    out = copy.deepcopy(summary)
    est = out.get("estimate_summary")
    if not isinstance(est, dict):
        return out

    def _scrub_dict(d: Dict[str, Any]) -> None:
        for key in list(d.keys()):
            lk = str(key).lower()
            if (
                "gbp" in lk
                or lk.endswith("_cost")
                or "unit_total" in lk
                or "extended_total" in lk
                or "material_cost" in lk
                or "labour_cost" in lk
                or "labor_cost" in lk
                or lk == "document_total_estimated_cost_gbp"
            ):
                d.pop(key, None)

    _scrub_dict(est)
    parts = est.get("part_estimates")
    if isinstance(parts, list):
        for row in parts:
            if isinstance(row, dict):
                _scrub_dict(row)
                me = row.get("material_estimate")
                if isinstance(me, dict):
                    _scrub_dict(me)
                pe = row.get("process_estimate")
                if isinstance(pe, dict):
                    _scrub_dict(pe)
    cb = est.get("cost_breakdown")
    if isinstance(cb, dict):
        _scrub_dict(cb)
    return out


def merge_bom_and_pipeline_rows(
    pdf_rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
    json_path: Path,
) -> List[Dict[str, Any]]:
    """
    Start from PDF BOM table rows (extraction_source 'table'). Overlay pipeline fields where
    item/dwg keys match. Append pipeline-only rows not represented on the BOM.
    """
    pipeline_rows = extract_from_pipeline_json(summary, json_path)
    by_key: Dict[str, Dict[str, Any]] = {}
    for prow in pipeline_rows:
        for key in _overlay_match_keys(prow):
            by_key[key] = dict(prow)

    merged: List[Dict[str, Any]] = []
    consumed: set[str] = set()

    for base in pdf_rows:
        row = dict(base)
        sup = None
        matched_key: Optional[str] = None
        for key in _overlay_match_keys(row):
            sup = by_key.get(key)
            if sup:
                matched_key = key
                break
        if sup:
            if matched_key:
                consumed.add(matched_key)
            for field in _JSON_OVERLAY_KEYS:
                val = sup.get(field)
                if val is not None and val != "":
                    row[field] = val
        merged.append(row)

    for k, prow in by_key.items():
        if k in consumed:
            continue
        merged.append(dict(prow))

    return merged


def _drawing_number_for_delete(summary: Dict[str, Any], json_path: Path, pdf_path: Path) -> str:
    try:
        return _drawing_number_from_json(summary, json_path)
    except Exception:
        return pdf_path.stem.upper()


def _delete_by_drawing(cursor, drawing_number: str) -> int:
    ident = bom_sql.qualified_table_sql(TABLE_NAME)
    cursor.execute(f"DELETE FROM {ident} WHERE drawing_number = ?", drawing_number)
    return int(cursor.rowcount or 0)


def process_one_pdf(
    pdf_path: Path,
    *,
    strip_pricing: bool,
    dry_run: bool,
    no_sql: bool,
    replace_drawing: bool,
) -> Tuple[int, int, Path, List[Dict[str, Any]]]:
    """
    Returns (merged_row_count, inserted_row_count_or_0_if_dry, json_path, pdf_bom_rows).
    """
    pdf_path = pdf_path.resolve()
    print(f"[PIPELINE] scan_file: {pdf_path.name}", flush=True)
    summary, output_paths = scan_file(pdf_path)
    json_path = Path(output_paths[0]).resolve()
    print(f"  JSON: {json_path}", flush=True)

    work_summary = _strip_estimate_pricing(summary) if strip_pricing else summary
    pdf_rows = extract_bom_tables(str(pdf_path))
    merged = merge_bom_and_pipeline_rows(pdf_rows, work_summary, json_path)
    print(f"  BOM table rows: {len(pdf_rows)}  merged+pipeline total: {len(merged)}", flush=True)

    if dry_run or no_sql:
        if merged:
            print(f"  [dry-run] sample keys: {sorted(merged[0].keys())}", flush=True)
        return len(merged), 0, json_path, pdf_rows

    conn = get_db_connection()
    cursor = conn.cursor()
    insert_columns = get_insert_column_names(cursor)
    col_lengths = get_text_column_lengths(cursor)
    drawing_number = _drawing_number_for_delete(summary, json_path, pdf_path)

    deleted = 0
    if replace_drawing:
        deleted = _delete_by_drawing(cursor, drawing_number)
        if deleted:
            print(f"  Deleted {deleted} existing row(s) for drawing_number={drawing_number!r}", flush=True)

    trimmed = 0
    for row in merged:
        cols, vals, was_trimmed = build_insert_row(row, insert_columns, col_lengths)
        if was_trimmed:
            trimmed += 1
        execute_dynamic_insert(cursor, TABLE_NAME, cols, vals)
    conn.commit()
    conn.close()
    if trimmed:
        print(f"  WARNING: {trimmed} row(s) trimmed for SQL column length", flush=True)
    print(f"  DONE: {len(merged)} row(s) -> {TABLE_NAME}", flush=True)
    return len(merged), len(merged), json_path, pdf_rows


def _stem_variants(stem: str) -> Set[str]:
    u = stem.upper()
    out = {u}
    m = re.match(r"^(.+)_(REV[A-Z]+\d?)$", u)
    if m:
        out.add(m.group(1))
    return out


def _list_reference_pdfs_recursive(search_roots: List[Path]) -> List[Path]:
    """All resolved *.pdf paths under search roots (deduped, stable order)."""
    seen: Set[Path] = set()
    out: List[Path] = []
    for root in search_roots:
        root = root.resolve()
        if not root.is_dir():
            print(f"  [WARN] reference search path is not a directory: {root}", flush=True)
            continue
        for p in root.rglob("*.pdf"):
            try:
                r = p.resolve()
            except OSError:
                continue
            if r in seen:
                continue
            seen.add(r)
            out.append(r)
    out.sort(key=lambda x: str(x).lower())
    return out


def _match_priority_for_token_in_filename(token: str, pdf_path: Path) -> Optional[int]:
    """
    Lower int = stronger match. None = no match.
    0 exact stem, 1 stem variant (strip _REV), 2 stem prefix, 3 drawing no substring in file name.
    """
    t = token.strip().upper()
    if not t:
        return None
    t = re.sub(r"^T\d+-", "", t)
    stem = pdf_path.stem.upper()
    fname = pdf_path.name.upper()
    if stem == t:
        return 0
    for v in _stem_variants(t):
        if stem == v:
            return 1
    if stem.startswith(t + "_") or stem.startswith(t + "-"):
        return 2
    if t in fname:
        return 3
    return None


def _resolve_token_to_pdf_path(
    token: str,
    pdf_catalog: List[Path],
) -> Optional[Path]:
    """
    Pick best PDF for a BOM drawing-number token using filename-based rules.
    Logs AMBIGUOUS when multiple files share the best priority tier after revision ranking.
    """
    raw = token.strip().upper()
    if not raw:
        return None
    t = re.sub(r"^T\d+-", "", raw)

    scored: List[Tuple[int, int, int, int, str, Path]] = []
    for p in pdf_catalog:
        pri = _match_priority_for_token_in_filename(t, p)
        if pri is None:
            continue
        scored.append((pri, -_revision_rank_from_path(p), len(p.stem), len(str(p)), str(p).lower(), p))

    if not scored:
        return None

    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    best_pri = scored[0][0]
    best_rev_sort = scored[0][1]
    tier = [row for row in scored if row[0] == best_pri and row[1] == best_rev_sort]
    uniq_paths: List[Path] = []
    seen_r: Set[Path] = set()
    for _, _, _, _, _, p in tier:
        rp = p.resolve()
        if rp in seen_r:
            continue
        seen_r.add(rp)
        uniq_paths.append(p)

    if len(uniq_paths) > 1:
        print(
            f"  [REFERENCES] AMBIGUOUS token {token!r}: {len(uniq_paths)} PDF(s) at match tier {best_pri}",
            flush=True,
        )
        for p in uniq_paths[:25]:
            print(f"      - {p}", flush=True)
        if len(uniq_paths) > 25:
            print(f"      … +{len(uniq_paths) - 25} more", flush=True)
        print(
            "  [REFERENCES] tie-break: shortest path, then shortest stem, then lexicographic (first wins)",
            flush=True,
        )

    uniq_paths.sort(key=lambda x: (len(str(x)), len(x.stem), str(x).lower()))
    return uniq_paths[0]


def collect_bom_reference_tokens(
    pdf_rows: List[Dict[str, Any]],
    parent_pdf: Path,
    token_pattern: Pattern[str],
) -> Set[str]:
    """Tokens from BOM rows that likely refer to other drawing PDFs."""
    parent_stems = _stem_variants(parent_pdf.stem)
    out: Set[str] = set()
    for row in pdf_rows:
        for field in (row.get("dwg_no"), row.get("item_number")):
            text = str(field or "").upper()
            for m in token_pattern.finditer(text):
                if m.lastindex is not None and m.lastindex >= 1:
                    tok = m.group(1).strip().upper()
                else:
                    tok = (m.group(0) or "").strip().upper()
                if len(tok) < 6:
                    continue
                if "FIXING" in tok:
                    continue
                if tok in parent_stems:
                    continue
                out.add(tok)
    return out


def run_pdf_with_bom_references(
    seed_pdf: Path,
    reference_search_dirs: List[Path],
    *,
    token_pattern: Pattern[str],
    strip_pricing: bool,
    dry_run: bool,
    no_sql: bool,
    replace_drawing: bool,
    transitive: bool,
    max_depth: int,
) -> None:
    """
    Process ``seed_pdf``, then resolve BOM references to PDFs under ``seed_pdf.parent`` and
    each ``reference_search_dirs`` entry, scanning each resolved file once (BFS if transitive).
    """
    seed_pdf = seed_pdf.resolve()
    search_roots: List[Path] = [seed_pdf.parent] + [d.resolve() for d in reference_search_dirs]
    pdf_catalog = _list_reference_pdfs_recursive(search_roots)
    print(
        f"[REFERENCES] Indexed {len(pdf_catalog)} PDF file(s) (recursive) under "
        + ", ".join(str(s) for s in search_roots),
        flush=True,
    )

    queue: deque[Tuple[Path, int]] = deque([(seed_pdf, 0)])
    seen: Set[Path] = set()
    while queue:
        rp, depth = queue.popleft()
        rp = rp.resolve()
        if rp in seen:
            continue
        if depth > max_depth:
            continue
        seen.add(rp)
        print(f"\n--- PDF depth={depth}: {rp.name} ---", flush=True)
        _, _, _, pdf_rows = process_one_pdf(
            rp,
            strip_pricing=strip_pricing,
            dry_run=dry_run,
            no_sql=no_sql,
            replace_drawing=replace_drawing,
        )
        expand = transitive or rp == seed_pdf
        if not expand:
            continue
        tokens = collect_bom_reference_tokens(pdf_rows, rp, token_pattern)
        if not tokens:
            continue
        print(f"  [REFERENCES] tokens from BOM: {sorted(tokens)[:40]}{' …' if len(tokens) > 40 else ''}", flush=True)
        for tok in sorted(tokens):
            tgt = _resolve_token_to_pdf_path(tok, pdf_catalog)
            if tgt is None:
                print(f"  [REFERENCES] unresolved: {tok}", flush=True)
                continue
            tr = tgt.resolve()
            if tr in seen:
                continue
            if depth + 1 > max_depth:
                print(f"  [REFERENCES] skip enqueue (max-depth): {tok} -> {tgt.name}", flush=True)
                continue
            print(f"  [REFERENCES] {tok} -> {tgt}", flush=True)
            queue.append((tr, depth + 1))


def _iter_dwg_index_pdfs(root: Path, stem_regex: str) -> List[Path]:
    root = root.resolve()
    rx = re.compile(stem_regex)
    out: List[Path] = []
    for p in root.rglob("*.pdf"):
        if rx.match(p.stem):
            out.append(p.resolve())
    return sorted(set(out), key=lambda x: str(x).lower())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scan PDF → JSON on disk + merge BOM tables with pipeline JSON → dbo.drawing_bom_items."
    )
    p.add_argument("--pdf", type=str, default=None, help="Single PDF: full scan + estimate + merge + SQL.")
    p.add_argument(
        "--reference-search-dir",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "With --pdf: extra folder(s) to index for *.pdf when resolving BOM dwg_no / part tokens "
            "(seed PDF's directory is always searched). Repeat for multiple dirs."
        ),
    )
    p.add_argument(
        "--reference-transitive",
        action="store_true",
        help="With --reference-search-dir: also follow BOM references found on child PDFs (BFS).",
    )
    p.add_argument(
        "--reference-max-depth",
        type=int,
        default=8,
        help="Max BFS depth when following BOM references (default 8).",
    )
    p.add_argument(
        "--reference-regex",
        type=str,
        default=None,
        metavar="REGEX",
        help=(
            "Regex for drawing-number tokens in BOM dwg_no / item_number. "
            "Prefer one capturing group (group 1) = token; if no group, whole match is used. "
            "Default: built-in pattern for GA-style numbers."
        ),
    )
    p.add_argument(
        "--strip-pricing",
        action="store_true",
        help="Strip GBP / cost fields from estimate_summary before building pipeline merge rows.",
    )
    p.add_argument(
        "--dwg-index-root",
        type=str,
        default=None,
        help="Folder: process each PDF whose stem matches --dwg-stem-regex (BOM + routing fields, pricing stripped).",
    )
    p.add_argument(
        "--dwg-stem-regex",
        type=str,
        default=_DEFAULT_DWG_STEM_REGEX,
        help="Regex applied to PDF filename stem (default: GA-style drawing numbers).",
    )
    p.add_argument("--dry-run", action="store_true", help="Parse and merge; print counts / sample keys; no SQL.")
    p.add_argument("--no-sql", action="store_true", help="Run scan and merge but skip database writes.")
    p.add_argument(
        "--replace-drawing",
        action="store_true",
        help="Before insert, DELETE FROM drawing_bom_items WHERE drawing_number = <resolved drawing>.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    has_pdf = bool(args.pdf)
    has_dwg_root = bool(args.dwg_index_root)
    ref_dirs = list(args.reference_search_dir or [])

    if has_pdf == has_dwg_root:
        print("ERROR: specify exactly one of --pdf <path> or --dwg-index-root <path>.")
        sys.exit(2)

    if has_dwg_root and ref_dirs:
        print("ERROR: --reference-search-dir is only valid with --pdf.")
        sys.exit(2)

    if has_pdf:
        seed = Path(args.pdf)
        if not seed.is_file():
            print(f"ERROR: PDF not found: {seed}")
            sys.exit(2)
        if ref_dirs:
            try:
                token_re = _compile_reference_token_pattern(args.reference_regex)
            except re.error as exc:
                print(f"ERROR: invalid --reference-regex: {exc}")
                sys.exit(2)
            run_pdf_with_bom_references(
                seed,
                ref_dirs,
                token_pattern=token_re,
                strip_pricing=args.strip_pricing,
                dry_run=args.dry_run,
                no_sql=args.no_sql,
                replace_drawing=args.replace_drawing,
                transitive=bool(args.reference_transitive),
                max_depth=int(args.reference_max_depth),
            )
        else:
            process_one_pdf(
                seed,
                strip_pricing=args.strip_pricing,
                dry_run=args.dry_run,
                no_sql=args.no_sql,
                replace_drawing=args.replace_drawing,
            )
        return

    root = Path(args.dwg_index_root)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        sys.exit(2)

    pdfs = _iter_dwg_index_pdfs(root, args.dwg_stem_regex)
    if not pdfs:
        print(f"No PDFs under {root} matched stem regex {args.dwg_stem_regex!r}")
        sys.exit(1)

    print(f"DWG index mode: {len(pdfs)} PDF(s) matched.\n")
    for pdf in pdfs:
        try:
            process_one_pdf(
                pdf,
                strip_pricing=True,
                dry_run=args.dry_run,
                no_sql=args.no_sql,
                replace_drawing=args.replace_drawing,
            )
        except Exception as exc:  # pragma: no cover - operational path
            print(f"ERROR [{pdf.name}]: {exc}", flush=True)
            raise


if __name__ == "__main__":
    main()
