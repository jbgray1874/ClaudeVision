import json
import os
import re
import shutil
import time
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from source_precedence import apply_field as _apply_field

try:
    import pdfplumber  # type: ignore
except ImportError:  # pragma: no cover
    pdfplumber = None

try:
    from pypdf import PdfReader  # type: ignore
except ImportError:  # pragma: no cover
    PdfReader = None

import config
from document_builder import build_document_writeup, merge_page_analysis
from estimator import append_rows_to_csv, build_estimate_input_rows, estimate_document
from extractor_patterns import build_textual_manufacturing_summary, normalize_text
from geometry_features import analyse_vector_features
from geometry_calibration import calibrate_page_geometry
from drawing_job_merge import (
    augment_summary_with_dxf,
    collect_dxf_paths_for_job,
    collect_dxf_paths_for_pdf_scan,
    is_flat_part_dxf,
)
from dxf_reader import analyse_dxf_document_geometry, extract_dxf_metadata, extract_dxf_pages, is_dxf_path
from geometry_analysis import analyse_document_geometry
from llm_extraction import reconcile_with_llm
from layout_zones import zone_boxes as _zone_boxes
from layout_zones import words_in_box as _words_in_box
from layout_zones import words_to_text as _words_to_text
from json_normaliser import normalise_json
from pricing_variance import build_pricing_variance_rows
from reconciliation import reconcile_page_analysis
from sql_export import build_run_metadata, write_postgres_insert_sql
from vision_extraction import extract_document_vision


def _find_manual_workbook(summary: Optional[Dict[str, Any]] = None, scan_label: Optional[str] = None):
    """Locate a manual estimate workbook for this job via the UNC share convention:
    <share>\\<year>\\<customer>\\<jobfolder>\\*.xls  — returns the first .xls found, else None.

    Summary-driven so the client-quote customer derivation
    (client_quote_html._customer_from_manual_path, which calls this as
    _find_manual_workbook(summary)) can resolve the manual — and therefore the real
    customer name — without needing the scan_label main.py has. Uses the SAME loosened
    job-number-token matching as main._find_manual_workbook (match on the numeric job
    number within the customer/year tree, not the exact folder name). Never raises.

    NOTE: main.py keeps its own copy of this lookup for the parity path. The two are
    intentionally kept in sync; consolidating them into a single source is a follow-up
    (deliberately not refactoring the working parity path here). See STATUS doc §6.
    """
    try:
        import glob
        share_root = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
        if not os.path.isdir(share_root):
            print(f"   [manual-lookup:customer] share not reachable: {share_root}", flush=True)
            return None
        # Derive the job number from the scan_label (if given) and the summary's job folder.
        cands_labels = []
        if scan_label:
            cands_labels.append(str(scan_label))
        if isinstance(summary, dict):
            _jf = summary.get("job_folder") or summary.get("job_output_stem")
            if _jf:
                cands_labels.append(os.path.basename(str(_jf)))
        job_nums = []
        for lab in cands_labels:
            jn = str(lab).split("-")[0].strip()
            jn = jn.split()[0] if jn else jn  # leading numeric token only
            if jn and jn not in job_nums:
                job_nums.append(jn)
        if not job_nums:
            print("   [manual-lookup:customer] no job number derivable from summary -> None", flush=True)
            return None
        candidates = []
        for year_dir in sorted(glob.glob(os.path.join(share_root, "20*")), reverse=True):
            for jn in job_nums:
                candidates += glob.glob(os.path.join(year_dir, "*", "*" + jn + "*", "*.xls"))
                candidates += glob.glob(os.path.join(year_dir, "*" + jn + "*", "*.xls"))
        seen = []
        for c in candidates:
            if os.path.basename(c).startswith("~$"):  # skip Excel lock files
                continue
            if c not in seen:
                seen.append(c)
        return seen[0] if seen else None
    except Exception as _mexc:
        print(f"   [manual-lookup:customer] error ({type(_mexc).__name__}: {_mexc}) -> None", flush=True)
        return None


def _reconcile_dualpath_into_part_estimates(summary, dp):
    """Push dual-path BOM-table fastener quantities/identities into the FINAL
    estimate_summary.part_estimates (the list the sheet actually reads).

    MUST be called AFTER estimate_document() — that is what builds part_estimates.
    The previous inline placement ran BEFORE estimate_document, so part_estimates
    did not exist yet, the isinstance guard skipped the block, and the corrections
    (self-clinch 1->4, knob 1->2, add BI-PEMSTUD) never reached the sheet. See the
    STATUS doc S3.3. Failure-isolated; fabricated parts are never touched.
    Returns (updated, added) counts.
    """
    import estimator as _E_recon
    import re as _re_recon

    rows = (dp or {}).get("rows") or []
    if not rows:
        return (0, 0)
    _es_recon = summary.get("estimate_summary") or {}
    _parts_recon = _es_recon.get("part_estimates")
    if _parts_recon is None:
        _parts_recon = summary.get("part_estimates")
    if not isinstance(_parts_recon, list):
        return (0, 0)

    def _is_fastener_row(_r):
        _d = (str(_r.get("description") or "") + " " +
              str(_r.get("part_code") or _r.get("code") or _r.get("part_number") or "")).upper()
        return any(_k in _d for _k in ("CLINCH", "NUT", "KNURL", "KNOB", "THUMB", "SCREW",
                   "PEM", "STUD", "RIVET", "THUM", "WASHER", "BOLT", "GLIDE"))

    def _dp_code(_r):
        return str(_r.get("part_code") or _r.get("code") or _r.get("part_number") or "").strip()

    def _dp_qty(_r):
        _q = _r.get("qty") or _r.get("quantity") or _r.get("qty_per_unit")
        try:
            return int(float(_q)) if _q is not None else None
        except (TypeError, ValueError):
            return None

    def _p_code(_p):
        return str(_p.get("part_number") or "").strip().upper()

    def _clean_code(_desc, _fallback):
        # ONE MAPPING, NOT A COPY PER READER. This table also has to run before the canonical
        # graph is built — that is how the wing nuts and PEM studs came to be in the workbook
        # and absent from the hierarchy — so it lives in part_identity and both paths call it.
        from part_identity import synthesise_bought_in_code
        return synthesise_bought_in_code(_desc, _fallback) or _fallback or "BI-FIXING"

    _added = _updated = 0
    for _r in rows:
        if not _is_fastener_row(_r):
            continue
        _code = _dp_code(_r)
        _qty = _dp_qty(_r)
        _desc = str(_r.get("description") or _code)
        if _qty is None or _qty <= 0:
            _qty = 1

        # 1) CODE match -> update qty, no add
        _cm = None
        if _code:
            for _p in _parts_recon:
                if _p_code(_p) == _code.upper():
                    _cm = _p
                    break
        if _cm is not None:
            # A quantity read from the PDF BOM table — rank 60. It must not displace the
            # assembly BOM the shop builds from, and the flag is gated on the write landing
            # so the record cannot claim a change the resolver refused.
            if _apply_field(_cm, "quantity", _qty, "bom_tree"):
                _cm.setdefault("review_flags", []).append(
                    f"Quantity set to {_qty} from dual-path BOM table read")
                _updated += 1
            print(f"   [recon-row] CODE-MATCH '{_desc}' (code {_code}) -> qty {_qty}", flush=True)
            continue

        # 2) TOKEN match vs bought-in parts -> dual-path qty wins
        _ctoks = _E_recon._bought_in_token_set({"description": _desc})
        _tm = None
        if _ctoks is not None:
            for _p in _parts_recon:
                _roles = _p.get("page_roles") or []
                if not ("bought_in" in _roles or _p_code(_p).startswith("BI-")):
                    continue
                _ptoks = _E_recon._bought_in_token_set(_p)
                if _ptoks is not None and _E_recon._bought_in_same_item(_ctoks, _ptoks):
                    _tm = _p
                    break
        if _tm is not None:
            if _tm.get("quantity") != _qty:
                _old = _tm.get("quantity")
                _apply_field(_tm, "quantity", _qty, "bom_tree")
                _tm.setdefault("review_flags", []).append(
                    f"Quantity corrected {_old} -> {_qty} from dual-path BOM table read (matched '{_desc}')")
                _updated += 1
            print(f"   [recon-row] TOKEN-MATCH '{_desc}' -> {_p_code(_tm)} qty {_qty}", flush=True)
            continue

        # 3) No match -> ADD clean bought-in row
        _cc = _clean_code(_desc, _code)
        if any(_p_code(_p) == _cc.upper() for _p in _parts_recon):
            print(f"   [recon-row] SKIP-ADD '{_desc}' -> {_cc} already present", flush=True)
            continue
        _parts_recon.append({
            "part_number": _cc, "description": _desc, "quantity": _qty,
            "pages": [], "page_roles": ["bought_in"], "materials": [],
            "surface_finishes": [], "colours": [], "thicknesses_mm": [],
            "weights": [], "textual_operations": ["handling"],
            "inferred_operations": [], "flat_pattern_detected": False,
            "assembly_candidate": False, "process_notes": [],
            "review_flags": [
                f"Added from dual-path BOM table read (code '{_code}' -> '{_cc}'), "
                f"qty {_qty} - price via waterfall, estimator to verify"],
            "confidence": {"overall": 0.0}, "source": "non_sdi_bom_row",
        })
        _added += 1
        print(f"   [recon-row] ADD {_cc} '{_desc}' qty {_qty}", flush=True)

    if _es_recon.get("part_estimates") is not None:
        _es_recon["part_estimates"] = _parts_recon
    elif isinstance(summary.get("estimate_summary"), dict) and \
            summary["estimate_summary"].get("part_estimates") is not None:
        summary["estimate_summary"]["part_estimates"] = _parts_recon
    else:
        summary["part_estimates"] = _parts_recon
    return (_updated, _added)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _is_excluded_doc(path: Path) -> bool:
    """A7: True if the file is a non-part document (setup/route/MO sheet) that must
    never be ingested as a drawing. Driven by config so future patterns inherit."""
    name = path.name.upper()
    pats = [str(p).upper() for p in getattr(config, "EXCLUDE_DOC_FILENAME_PATTERNS", [])]
    return any(p in name for p in pats)


def list_input_files(search_root: Path = config.DRAWINGS_DIR, drawing_pattern: str = "*") -> List[Path]:
    if not search_root.exists():
        return []
    paths = sorted(
        [
            path
            for path in search_root.glob(drawing_pattern)
            if path.is_file() and path.suffix.lower() in config.SUPPORTED_EXTENSIONS
            and not _is_excluded_doc(path)
        ]
    )
    job_cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    if job_cfg.get("exclude_flat_dxf_from_batch", True):
        paths = [path for path in paths if not is_flat_part_dxf(path)]
    return paths


def group_input_files_by_folder(files: Sequence[Path]) -> Dict[Path, List[Path]]:
    """Group PDF paths by parent directory for folder-as-job scanning."""
    groups: Dict[Path, List[Path]] = {}
    for path in files:
        if path.suffix.lower() != ".pdf":
            continue
        if _is_excluded_doc(path):  # A7: skip setup/route/MO sheets
            continue
        key = path.parent.resolve()
        groups.setdefault(key, []).append(path)
    for folder in groups:
        groups[folder] = sorted(groups[folder], key=lambda p: p.name.lower())
    return groups


def _normalize_bom_part_key(part_number: Any) -> str:
    try:
        from part_identity import normalize_part_code

        return normalize_part_code(part_number)
    except Exception:
        pn = re.sub(r"\s*-\s*", "-", str(part_number or "").strip())
        return re.sub(r"\s+", "", pn).upper()


def _score_primary_job_pdf(pdf_path: Path, summary: Dict[str, Any]) -> int:
    """Prefer the top-level GA / richest BOM as the job anchor PDF."""
    name = pdf_path.name.upper()
    score = 0
    if re.search(r"\bGA\b", name) or "- GA" in name or "_GA" in name:
        score += 20
    if re.search(r"\b\d{4}\b", name):
        score += 5
    if "WALL BAY" in name or "STANDARD" in name:
        score += 3
    bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
    score += min(len(bom_rows), 30)
    score += min(int(summary.get("page_count") or 0), 10)
    return score


def _merge_bom_rows(winner: Dict[str, Any], loser: Dict[str, Any]) -> None:
    """Fold the losing drawing's reading of one BOM line into the row we are keeping.

    Both rows were read off a printed parts table, so both are `bom_tree` and neither
    outranks the other: the loser fills what the winner left blank, and where the two
    disagree the winner stands and the disagreement is written onto it. `source_pdf`
    names which drawing this row was taken from and must keep naming the winner's.
    """
    try:
        from record_merge import merge_records, BOOKKEEPING_FIELDS
    except Exception:                                              # pragma: no cover
        return
    _notes = merge_records(
        winner, loser, winner_source="bom_tree", loser_source="bom_tree",
        decided=("part_number", "bom_parent"),
        skip=tuple(BOOKKEEPING_FIELDS) + ("source_pdf",),
        label=f"BOM line {winner.get('part_number')} also on "
              f"{loser.get('source_pdf') or 'another drawing'}")
    if _notes and os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}:
        for _n in _notes:
            print(f"   [bom-merge] {_n}", flush=True)


def _bom_row_merge_preferred(
    row: Dict[str, Any],
    existing: Dict[str, Any],
    row_pdf: Path,
    primary_pdf: Path,
) -> bool:
    if row_pdf.resolve() == primary_pdf.resolve() and existing.get("source_pdf") != primary_pdf.name:
        return True
    if existing.get("source_pdf") == primary_pdf.name and row_pdf.resolve() != primary_pdf.resolve():
        return False
    if row.get("quantity") and not existing.get("quantity"):
        return True
    if len(str(row.get("description") or "")) > len(str(existing.get("description") or "")):
        return True
    return False


def _codes_claimed_by_the_hierarchy(summary: Dict[str, Any]) -> List[str]:
    """Every code some assembly names as a child, from all three hierarchy sources.

    WHICH OF TWO SPELLINGS OF ONE PART TO KEEP is decided by length unless something says
    otherwise, and this is what says otherwise. 12422-24 carried "79814P" as a child of the
    GA and "79814P613" as a child of nothing — the same four screws, and the length rule
    would have kept the one the drawing does not reference, leaving the disconnected node it
    was supposed to remove.

    Read from the parts themselves (assembly_children, written by the SolidWorks pass and
    the description rule) and from the whole-job extract's assemblies. Every source is
    unioned rather than ranked: this asks only "did ANY reading of this job claim this
    code", which is a weaker question than whose tree is right, and the weaker question is
    the one that has an answer here.
    """
    claimed: List[str] = []
    for part in ((summary.get("manufacturing_writeup") or {}).get("parts") or []):
        if not isinstance(part, dict):
            continue
        for kid in (part.get("assembly_children") or []):
            if str(kid or "").strip():
                claimed.append(str(kid))
    for holder in (summary.get("llm_full_extract"), summary.get("llm_extract")):
        if not isinstance(holder, dict):
            continue
        for assembly in (holder.get("assemblies") or []):
            if not isinstance(assembly, dict):
                continue
            for edge in (assembly.get("children") or []):
                code = edge.get("part_number") if isinstance(edge, dict) else edge
                if str(code or "").strip():
                    claimed.append(str(code))
    return claimed


def _merge_truncated_bom_codes(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One screw extracted twice is one BOM line, not two unpriceable ones.

    12422-24's pooled BOM carried "79814P613  3.5 x 16mm Pan Head Wood Screw" qty 4 AND
    "79814P  3.5 x 16mm Pan Head Wood Screw" qty 4 — the same four screws, read twice, once
    with the code truncated. The stem is not a code, so UDEF has no row for it and that line
    could never be priced whatever we asked; and the quantity sat on the sheet twice for an
    estimator to spot and merge by hand.

    The merge is refused unless the DESCRIPTIONS agree as well as the codes. Two codes that
    share a prefix and describe different parts are two parts, and a prefix alone is a weak
    enough signal that it must not act on its own. Quantity is taken as the LARGER of the
    two rather than the sum: these are two readings of one line, not two lines.

    A labelled cell — "VITAL PARTS: LOW068" — has its label stripped here too, so the code
    that reaches UDEF is the one the supplier would recognise.
    """
    from part_identity import normalize_part_code, strip_code_label, stem_duplicate_target

    if not rows:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        _raw = row.get("part_number") or row.get("part_code") or ""
        _clean = strip_code_label(_raw)
        if _clean and _clean != str(_raw).strip():
            row["part_number"] = _clean
            row.setdefault("review_flags", []).append(
                f"BOM code '{_raw}' carried a label; read as '{_clean}' so it can be looked up")

    def _desc(r):
        return " ".join(str(r.get("description") or "").upper().split())

    _codes = [str(r.get("part_number") or "") for r in rows if isinstance(r, dict)]
    _by_code = {normalize_part_code(c): r for c, r in zip(_codes, rows)}
    out: List[Dict[str, Any]] = []
    for row, code in zip(rows, _codes):
        if not isinstance(row, dict):
            out.append(row)
            continue
        target = stem_duplicate_target(code, [c for c in _codes if c != code])
        keeper = _by_code.get(target) if target else None
        if keeper is None or not _desc(row) or _desc(row) != _desc(keeper):
            out.append(row)
            continue
        try:
            _q_stem = float(row.get("quantity") or row.get("qty") or 0)
            _q_keep = float(keeper.get("quantity") or keeper.get("qty") or 0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if _q_stem > _q_keep:
            # A raw BOM ROW at extraction time, before any part record exists for the
            # resolver to arbitrate on. Not a new observation: two readings of ONE printed
            # cell, and the larger is the one that read the whole line rather than a
            # truncation of it. No source is displaced.
            keeper["quantity"] = _q_stem   # precedence: direct-write ok — reconciles two readings of one raw BOM cell
        keeper.setdefault("review_flags", []).append(
            f"BOM line '{code}' merged into '{target}': same description, and '{code}' is a "
            f"truncation of it. One item read twice — the quantity is the larger of the two "
            f"({_q_keep:g} and {_q_stem:g}), not their sum.")
        print(f"   [bom] merged truncated code '{code}' into '{target}' "
              f"(same description, qty {max(_q_stem, _q_keep):g})")
    return out


def merge_job_pdf_summaries(
    partials: Sequence[Tuple[Path, Dict[str, Any]]],
    job_folder: Path,
) -> Tuple[Dict[str, Any], Path]:
    """Merge per-PDF extract summaries into one job-level summary before writeup/estimate."""
    if not partials:
        raise ValueError("merge_job_pdf_summaries requires at least one PDF summary")

    primary_pdf, primary_summary = max(
        partials,
        key=lambda item: _score_primary_job_pdf(item[0], item[1]),
    )

    merged: Dict[str, Any] = {
        "source_file": f"{job_folder.name}.json",
        "full_path": str(job_folder.resolve()),
        "job_folder": str(job_folder.resolve()),
        "job_output_stem": job_folder.name,
        "scan_mode": "folder_as_job",
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "job_source_pdfs": [],
        "pages": [],
        "manual_review_items": [],
        "detected_labels": [],
        "pattern_summary": {"part_numbers": [], "dates": [], "revision_matches": [], "dimensions_mm": []},
        "document_analysis": dict(primary_summary.get("document_analysis") or {}),
        "output_targets": dict(primary_summary.get("output_targets") or {}),
        "pdf_metadata": dict(primary_summary.get("pdf_metadata") or {}),
    }

    bom_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    part_numbers: set[str] = set()
    dates: set[str] = set()
    revisions: set[str] = set()
    dimensions: set[str] = set()
    labels: set[str] = set()
    geom_pages: List[Dict[str, Any]] = []
    job_page = 0

    for pdf_path, summary in sorted(partials, key=lambda item: item[0].name.lower()):
        merged["job_source_pdfs"].append(
            {
                "name": pdf_path.name,
                "path": str(pdf_path.resolve()),
                "page_count": summary.get("page_count"),
            }
        )
        # Global page numbers assigned to this PDF's pages, in order. Used below
        # to re-align this PDF's geometry pages onto the same canonical scheme.
        pdf_global_pages: List[int] = []
        for page in summary.get("pages") or []:
            job_page += 1
            page_copy = dict(page)
            page_copy["source_pdf_path"] = str(pdf_path.resolve())
            page_copy["source_pdf_name"] = pdf_path.name
            # Canonical page number for the merged job. Each source PDF numbers
            # its own pages from 1, so without this every PDF's page 1/2 collides
            # in document_builder's page_lookup (keyed on page_number) and the
            # last PDF in wins — cross-wiring one part's text/geometry onto
            # another (the folder-as-job "Led"/bought_in regression). Make the
            # job-wide number canonical and keep the per-PDF original for display.
            page_copy["source_page_number"] = page_copy.get("page_number")
            page_copy["page_number"] = job_page
            page_copy["job_page_number"] = job_page
            pdf_global_pages.append(job_page)
            merged["pages"].append(page_copy)
        for item in summary.get("manual_review_items") or []:
            review = dict(item)
            review["source_pdf"] = pdf_path.name
            merged["manual_review_items"].append(review)

        doc = summary.get("document_analysis") or {}
        for row in doc.get("bom_rows") or []:
            code = _normalize_bom_part_key(row.get("part_number"))
            if not code:
                continue
            row_copy = dict(row)
            row_copy["source_pdf"] = pdf_path.name
            # THE LINE, NOT THE CODE. This kept one row per part number across the whole
            # folder, so an enquiry with two general arrangements lost one of every fastener
            # line that both drawings used — the quantity and the owner with it, before any
            # other pass could see either. The parent comes from the sheet's own title block;
            # where no sheet named one, the key falls back to the code and this behaves
            # exactly as it did, which is what makes it safe to turn on for every job.
            key = (_normalize_bom_part_key(row.get("bom_parent")),
                   code,
                   normalize_text(str(row.get("description") or "")).upper())
            existing = bom_by_key.get(key)
            if existing is None:
                bom_by_key[key] = row_copy
            else:
                # TWO DRAWINGS PRINTING ONE LINE. The preference rule below decides which
                # ROW to keep — the primary GA's, on principle, because it is the sheet the
                # job is quoted from. It was then kept WHOLESALE, so where the primary's
                # table clipped a column and the other drawing printed it, the winning row
                # carried the blank and the reading that had the number was dropped. Both
                # readings come off a parts table and rank equally, so the loser can fill
                # gaps and displace nothing; where they genuinely differ, the disagreement
                # is recorded on the surviving row instead of vanishing with it.
                _prefer_new = _bom_row_merge_preferred(row_copy, existing, pdf_path, primary_pdf)
                _winner, _loser = ((row_copy, existing) if _prefer_new
                                   else (existing, row_copy))
                _merge_bom_rows(_winner, _loser)
                bom_by_key[key] = _winner

        ps = summary.get("pattern_summary") or {}
        part_numbers.update(ps.get("part_numbers") or [])
        dates.update(ps.get("dates") or [])
        revisions.update(ps.get("revision_matches") or [])
        dimensions.update(str(v) for v in (ps.get("dimensions_mm") or []))
        labels.update(summary.get("detected_labels") or [])

        gs = summary.get("geometry_summary") or {}
        for gi, gp in enumerate(gs.get("pages") or []):
            gpc = dict(gp)
            gpc["source_pdf_path"] = str(pdf_path.resolve())
            gpc["source_pdf_name"] = pdf_path.name
            # Geometry pages are produced in the same order as this PDF's pages,
            # so align them to the same canonical numbers by position. Without
            # this the geometry pages keep per-PDF numbers and re-collide.
            gpc["source_page_number"] = gpc.get("page_number")
            if gi < len(pdf_global_pages):
                gpc["page_number"] = pdf_global_pages[gi]
            geom_pages.append(gpc)

    merged["page_count"] = len(merged["pages"])
    merged["detected_labels"] = sorted(labels)
    merged["pattern_summary"] = {
        "part_numbers": sorted(part_numbers),
        "dates": sorted(dates),
        "revision_matches": sorted(revisions),
        "dimensions_mm": sorted(dimensions, key=lambda v: float(v) if re.match(r"^\d", str(v)) else 0),
    }
    merged_doc = dict(merged.get("document_analysis") or {})
    merged_doc["bom_rows"] = _merge_truncated_bom_codes(list(bom_by_key.values()))
    merged["document_analysis"] = merged_doc

    primary_gs = primary_summary.get("geometry_summary") or {}
    merged["geometry_summary"] = {
        **primary_gs,
        "pages": geom_pages,
        "notes": f"Merged geometry from {len(partials)} PDF(s) in {job_folder.name}",
        "job_folder": str(job_folder.resolve()),
    }
    merged["primary_pdf"] = {
        "name": primary_pdf.name,
        "path": str(primary_pdf.resolve()),
    }
    if os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}:
        print(
            f"[DEBUG] folder-as-job page renumber: {len(merged['pages'])} page(s), "
            f"job_page_number is canonical page_number",
            flush=True,
        )
    return merged, primary_pdf


def extract_pdf_summary(pdf_path: Path) -> Dict[str, Any]:
    """PDF extract + geometry only — no writeup, DXF merge, or estimate."""
    skip_vision = os.getenv("SKIP_VISION_EXTRACTION", "").lower() in {"1", "true", "yes"}
    plumber_pages = extract_with_pdfplumber(pdf_path)
    pypdf_pages = extract_with_pypdf(pdf_path)
    vision_pages = [] if skip_vision else extract_document_vision(pdf_path)
    summary = summarise_document(pdf_path, plumber_pages, pypdf_pages, vision_pages=vision_pages)
    processed_pages = summary.get("pages", [])
    geometry_results = analyse_document_geometry(processed_pages, pdf_path=pdf_path)
    for i, page in enumerate(processed_pages):
        if i < len(geometry_results.get("pages", [])):
            page["geometry"] = geometry_results["pages"][i].get("geometry", {})
            page["calibration"] = geometry_results["pages"][i].get("calibration", {})
    summary["geometry_summary"] = {
        "document_geometry_reliability": geometry_results.get("document_geometry_reliability", 0.0),
        "overall_confidence": geometry_results.get("overall_confidence", 0.0),
        "pages": geometry_results.get("pages", []),
        "fitz_available": geometry_results.get("fitz_available", False),
        "pdf_path_recovered": geometry_results.get("pdf_path_recovered", False),
        "pages_with_fitz_drawings": geometry_results.get("pages_with_fitz_drawings", 0),
        "notes": "Fitz vector drawings + title-block/text scale calibration",
        "source_pdf_path": str(pdf_path.resolve()),
    }
    return summary


def scan_folder_job(
    job_folder: Path,
    pdf_paths: Sequence[Path],
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    """Scan all PDFs in a folder as one job — pooled BOM, one DXF pass, one estimate."""
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    started = time.time()
    pdfs = [Path(p) for p in pdf_paths if Path(p).suffix.lower() == ".pdf"]
    if not pdfs:
        raise ValueError(f"No PDF files to scan in job folder {job_folder}")

    print(f"   -> Folder-as-job: {job_folder.name} ({len(pdfs)} PDF(s))")
    partials: List[Tuple[Path, Dict[str, Any]]] = []
    for pdf_path in sorted(pdfs, key=lambda p: p.name.lower()):
        print(f"      • Extracting {pdf_path.name}")
        partials.append((pdf_path, extract_pdf_summary(pdf_path)))

    merged, anchor_pdf = merge_job_pdf_summaries(partials, job_folder)
    bom_count = len((merged.get("document_analysis") or {}).get("bom_rows") or [])
    print(f"   -> Pooled BOM: {bom_count} line(s); anchor PDF: {anchor_pdf.name}")

    return _finalize_scan_summary(
        merged,
        started,
        debug,
        geometry_summary=merged.get("geometry_summary"),
        pdf_path=anchor_pdf,
        job_folder=job_folder,
        attach_dxf_paths=attach_dxf_paths,
        auto_discover_dxf=auto_discover_dxf,
    )


def _infer_page_role(page_text: str, bom_text: str, title_block_text: str) -> Dict[str, Any]:
    full_text = normalize_text(f"{page_text} {bom_text} {title_block_text}")
    part_numbers = re.findall(config.PART_NUMBER_PATTERN, full_text, flags=re.IGNORECASE)
    _junk_sfx = (
        " - ALUMINIUM", " - ALUMINUM", " - STEEL", " - TIMBER", " - PLYWOOD",
        " - CLEAR", " - COATED", " - MATT", " - BLACK", " - WHITE",
    )
    _junk_tokens = [str(t).upper() for t in getattr(config, "JUNK_PART_TOKENS", [])]
    part_numbers = [
        p for p in part_numbers
        if not any(p.upper().endswith(s.upper()) for s in _junk_sfx)
        and not re.match(r"^\d{4}\s*-\s*[A-Z]{2,}$", p.upper())
        and not p.upper().startswith(("C-C", "MMM", "UPC-", "RAL"))
        and not any(tok in p.upper() for tok in _junk_tokens)   # A9: drop title-block artifacts
    ]
    bom_row_count = len(re.findall(config.QTY_TABLE_ROW_PATTERN, full_text, flags=re.IGNORECASE))
    unique_part_numbers = sorted(set(part_numbers))
    detail_cues = any(token in full_text.upper() for token in ["FLAT PATTERN", "DETAIL "])
    drawing_assembly_hint = "ASSEMBLY" in normalize_text(title_block_text).upper()
    title_block_drawing_numbers = re.findall(config.DRAWING_NUMBER_PATTERN, normalize_text(title_block_text), flags=re.IGNORECASE)
    title_block_drawing_number_count = len(title_block_drawing_numbers)
    page_text_upper = normalize_text(page_text).upper()
    bom_header_detected = all(token in page_text_upper for token in ["ITEM", "DWG NO", "QTY"])

    signals: List[str] = []
    primary_role = "detail"

    if bom_row_count > 0:
        signals.append("bom_rows_detected")
    if len(unique_part_numbers) > 1:
        signals.append("multiple_part_numbers_detected")
    if drawing_assembly_hint:
        signals.append("assembly_title_detected")
    if detail_cues:
        signals.append("flat_pattern_detected")
    if bom_header_detected:
        signals.append("bom_header_detected")
    if title_block_drawing_number_count == 1:
        signals.append("single_title_block_drawing_number")

    if detail_cues and title_block_drawing_number_count == 1:
        primary_role = "detail"
    elif bom_header_detected and (bom_row_count > 0 or len(unique_part_numbers) > 1):
        primary_role = "assembly"
    elif bom_row_count >= 2 and len(unique_part_numbers) > 1:
        primary_role = "assembly"
    elif detail_cues and len(unique_part_numbers) <= 1:
        primary_role = "detail"
    elif drawing_assembly_hint and len(unique_part_numbers) <= 1:
        primary_role = "detail"

    return {
        "primary_role": primary_role,
        "signals": signals,
    }


def _calibrate_title_block_region(title_block_text: str, full_text: str) -> Dict[str, Any]:
    title_labels = find_labels(title_block_text)
    full_labels = find_labels(full_text)
    title_score = len(title_labels)
    full_score = len(full_labels)
    use_region_text = title_score >= max(3, full_score // 2)
    return {
        "use_region_text": use_region_text,
        "region_label_count": title_score,
        "full_page_label_count": full_score,
        "confidence": round(min(1.0, title_score / 8), 2),
    }


def extract_with_pdfplumber(pdf_path: Path) -> List[Dict[str, Any]]:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed.")

    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            words = page.extract_words() or []
            zones = _zone_boxes(float(page.width), float(page.height))
            title_block_words = _words_in_box(words, zones["title_block"])
            bom_words = _words_in_box(words, zones["bom"])
            notes_words = _words_in_box(words, zones["notes"])
            revision_words = _words_in_box(words, zones["revision"])

            title_block_text = _words_to_text(title_block_words)
            bom_text = _words_to_text(bom_words)
            notes_text = _words_to_text(notes_words)
            revision_text = _words_to_text(revision_words)
            page_role = _infer_page_role(text, bom_text, title_block_text)
            title_block_calibration = _calibrate_title_block_region(title_block_text, text)

            pages.append(
                {
                    "page_number": idx,
                    "text": text,
                    "normalized_text": normalize_text(text),
                    "word_count": len(words),
                    "words": words,
                    "page_width": float(page.width),
                    "page_height": float(page.height),
                    "region_text": {
                        "title_block": title_block_text,
                        "bom": bom_text,
                        "notes": notes_text,
                        "revision": revision_text,
                    },
                    "layout_regions": {
                        "boxes": zones,
                        "counts": {
                            "title_block_words": len(title_block_words),
                            "bom_words": len(bom_words),
                            "notes_words": len(notes_words),
                            "revision_words": len(revision_words),
                        },
                    },
                    "page_role": page_role,
                    "title_block_calibration": title_block_calibration,
                }
            )
    return pages


def extract_with_pypdf(pdf_path: Path) -> List[str]:
    if PdfReader is None:
        return []
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def extract_pdf_metadata(pdf_path: Path) -> Dict[str, Any]:
    if PdfReader is None:
        return {}
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata or {}
        return {str(key): str(value) for key, value in metadata.items()}
    except Exception:
        return {}


def find_labels(text: str) -> List[str]:
    found: List[str] = []
    upper_text = (text or "").upper()
    for label in config.TITLE_BLOCK_LABELS:
        if label in upper_text:
            found.append(label)
    return found


def extract_patterns(text: str) -> Dict[str, Any]:
    normalized = normalize_text(text)
    _junk_sfx = (
        " - ALUMINIUM", " - ALUMINUM", " - STEEL", " - TIMBER", " - PLYWOOD",
        " - CLEAR", " - COATED", " - MATT", " - BLACK", " - WHITE",
    )

    def _valid_pn(pn: str) -> bool:
        up = pn.upper()
        if up in {
            "TIMBER-BASED",
            "TIMBER BASED",
            "ALUMINIUM-BASED",
            "MILD STEEL",
            "STAINLESS STEEL",
            "ALUMINIUM",
            "ALUMINUM",
        }:
            return False
        if any(up.endswith(s.upper()) for s in _junk_sfx):
            return False
        if any(up.startswith(s.upper()) for s in ("C-C", "MMM-YY", "UPC-", "RAL")):
            return False
        if re.match(r"^\d{4}\s*-\s*[A-Z]{2,}$", up):
            return False
        if "-" in pn and len(pn) < 6:
            return False
        return True

    _raw_pns = re.findall(config.PART_NUMBER_PATTERN, normalized, flags=re.IGNORECASE)
    return {
        "part_numbers": sorted(set(p for p in _raw_pns if _valid_pn(p))),
        "dates": sorted(set(re.findall(config.DATE_PATTERN, normalized, flags=re.IGNORECASE))),
        "revision_matches": sorted(set(re.findall(config.REVISION_PATTERN, normalized, flags=re.IGNORECASE))),
        "dimensions_mm": sorted(set(re.findall(config.DIMENSION_PATTERN, normalized, flags=re.IGNORECASE)))[:500],
    }


def _is_revision_table_noise(text: str) -> bool:
    """
    Return True if a colour/finish string is revision-table or instruction text,
    not a real finish or colour specification.
    """
    if not text:
        return False
    upper = text.upper().strip()
    noise_markers = [
        "REFER TO ASSEMBLY LEVEL",
        "SEE ASSEMBLY DRAWING",
        "DO NOT SCALE",
        "UNLESS OTHERWISE STATED",
        "CHANGED TO ",
        "MECHANISM CHANGED",
        "NOTE REMOVED",
        "NOTE ADDED",
        "BRACKET ADJUSTED",
        "CODES ADDED",
        "FIRST ISSUE",
        "DRG NO DESCRIPTION DATE",
        "REVISION TABLE",
    ]
    return any(marker in upper for marker in noise_markers) or len(text) > 120


def _clean_field_list(values: List[str], field: str) -> List[str]:
    """Filter out revision-table noise from colour/finish fields."""
    if field not in ("colours", "surface_finishes"):
        return values
    return [v for v in (values or []) if not _is_revision_table_noise(v)]


def _page_drawing_number(page: Dict[str, Any]) -> str:
    """The drawing this page IS, from its own title block — "" when it does not say.

    Deliberately the title block and nothing else. A drawing number appearing anywhere else
    on a sheet is usually a reference to another sheet, and taking one would make a detail
    claim to own the assembly that references it.
    """
    text = normalize_text(str((page.get("region_text") or {}).get("title_block") or ""))
    if not text:
        return ""
    found = re.findall(config.DRAWING_NUMBER_PATTERN, text, flags=re.IGNORECASE)
    if not found:
        # THE LABEL IS NOT THE NUMBER. DRAWING_NUMBER_PATTERN requires a literal "DWG NO"
        # or "DRAWING NO" immediately before the code, so a title block whose label does
        # not survive text extraction next to its number yields nothing — and
        # assembly_page_owners then falls back to the FILE STEM, which matches no part the
        # job knows, so the page can own nothing.
        #
        # That is why job 12392's bolt stayed disconnected with a page in hand: page 6 is
        # an assembly page, the record carried source_page=6 into both compiler pools, and
        # the only thing missing was the page's own name.
        #
        # The shape rule needs no label. It is the same authority the BOM reader's title
        # block read uses — part_code_conventions.looks_like_a_drawing_number — which finds
        # 12392-04-GA on this very sheet. Adjacent tokens are joined first so a spaced
        # "1282 - GA" reads as one code, and the LONGEST match wins so "12392-02" cannot
        # beat "12392-02-GA" and reparent the sheet onto its own parent.
        # THE SHAPE RULE, NOT THE LABEL. Two things it must not do.
        #
        # It must not swallow the description: joining greedily turned
        # "12392-04-GA MOD BRACKET SET" into "12392-04-GAMODBRACKETSET", which passes the
        # shape test because every word is alphanumeric. So tokens are only joined across
        # a literal "-", which is the spaced form a drawing prints as "1282 - GA" and is
        # never how a description continues.
        #
        # And it must not take a prefix: "12392-02 - GA" reads as "12392-02" if single
        # tokens simply win, and that is the sheet's PARENT — every row on the page would
        # be reparented one level up.
        import part_code_conventions as _pcc
        _toks = [t for t in re.split(r"\s+", text.upper()) if t]
        _codes = []
        _i = 0
        while _i < len(_toks):
            if not _pcc.looks_like_a_drawing_number(_toks[_i]) and not (
                    _i + 2 < len(_toks) and _toks[_i + 1] == "-"):
                _i += 1
                continue
            _run, _j = _toks[_i], _i
            while _j + 2 < len(_toks) and _toks[_j + 1] == "-" \
                    and _pcc.looks_like_a_drawing_number(_run + "-" + _toks[_j + 2]):
                _run = _run + "-" + _toks[_j + 2]
                _j += 2
            if _pcc.looks_like_a_drawing_number(_run) and _run not in _codes:
                _codes.append(_run)
            _i = _j + 1
        # ONE, OR NONE, exactly as the labelled path: a region holding two drawing numbers
        # has caught a cross-reference as well as its own, and naming the wrong one gives
        # every row on the page the wrong owner.
        if len(_codes) == 1:
            found = _codes

    # ONE, OR NONE. A title block region that caught two drawing numbers has caught a
    # cross-reference as well as its own, and there is no way to tell which is which from
    # here. Naming the wrong one would give every row on the page the wrong owner.
    uniq = []
    for f in found:
        c = normalize_text(str(f)).upper().strip()
        if c and c not in uniq:
            uniq.append(c)
    return uniq[0] if len(uniq) == 1 else ""


def assembly_page_owners(summary: Dict[str, Any]) -> Dict[int, str]:
    """page number -> the drawing that page IS, for pages carrying an assembly BOM.

    THE ROWS ARE NOT ALWAYS WHERE THE ATTRIBUTION LOOKS. attribute_bom_rows_to_source_pages
    stamps document_analysis["bom_rows"], which is what the deterministic text reader
    produces — and on job 12392 that reader found nothing at all. The BOM arrived from the
    vision extract and from rows synthesised out of the costed parts, neither of which
    carries a parent, so the hierarchy source had nothing to consume and every part on the
    second drawing stayed an orphan. The chain was correct and wired to an empty tap.

    A part still knows which PAGES it appeared on, whatever read it. That is the fact this
    exposes: the page's own role, which the engine already infers, and the drawing that page
    belongs to. A part on an ASSEMBLY page of a drawing is listed by that drawing.

    ASSEMBLY PAGES ONLY, and that is the whole safety of it. A detail sheet is not an owner —
    it is one part drawn large — so giving it children would invent a parent for every part
    that merely has its own sheet. The role is read from the page, not guessed from the file
    name; where the title block does not name a drawing the file's own stem stands in, and
    the compiler refuses any owner it cannot already identify, so a descriptive file name
    resolves to nothing and no edge is made.
    """
    owners: Dict[int, str] = {}
    for page in (summary.get("pages") or []):
        if not isinstance(page, dict):
            continue
        role = str(((page.get("page_role") or {}) if isinstance(page.get("page_role"), dict)
                    else {}).get("primary_role") or "").strip().lower()
        if role != "assembly":
            continue
        number = page.get("page_number")
        if number is None:
            continue
        drawing = _page_drawing_number(page)
        if not drawing:
            stem = str(page.get("source_pdf_name") or "")
            if stem.lower().endswith(".pdf"):
                stem = stem[:-4]
            drawing = normalize_text(stem).upper().strip()
        if drawing:
            owners[int(number)] = drawing
    return owners


def attribute_bom_rows_to_source_pages(rows: List[Dict[str, Any]],
                                       pages: List[Dict[str, Any]]) -> int:
    """Stamp each BOM row with the page that printed it, and that page's drawing number.

    THE OWNERSHIP IS NOT LOST LATER — IT IS NEVER RECORDED. summarise_document joins every
    page's BOM region into one string and runs one regex over the lot, so a row arrives with
    an item number, a code, a description and a quantity, and no idea which sheet it was on.
    Every downstream attempt to recover the tree is therefore reconstructing something the
    first read threw away, which is why it keeps half-working.

    This does NOT change which rows are read. The joined-text pass runs exactly as before and
    produces exactly the same rows; this walks them afterwards and says where each came from.
    Additive by construction: a row that cannot be placed is left alone and carries no parent,
    which is the same "" every row carried before.

    TWO OF THE SAME CODE ON TWO SHEETS ARE TWO ROWS, and they must not both be attributed to
    the first sheet. Each page's occurrences are consumed as they are claimed, so a fastener
    listed on the panel GA and again on the bracket GA gets one row per sheet — which is the
    whole point, because those are different quantities under different owners.

    Returns how many rows were placed, so the caller can say when it placed none.
    """
    if not rows or not pages:
        return 0
    # What each page's BOM region says, and how many times it names each code.
    page_info: List[Tuple[Dict[str, Any], str, str]] = []
    for page in pages:
        region = (page.get("region_text") or {})
        text = normalize_text(f"{region.get('bom') or ''} {region.get('notes') or ''}").upper()
        if text.strip():
            page_info.append((page, text, _page_drawing_number(page)))
    if not page_info:
        return 0

    remaining: List[Dict[str, int]] = []
    for _page, text, _dwg in page_info:
        counts: Dict[str, int] = {}
        for row in rows:
            code = str(row.get("part_number") or "").upper().strip()
            if code and code not in counts:
                counts[code] = text.count(code)
        remaining.append(counts)

    placed = 0
    for row in rows:
        code = str(row.get("part_number") or "").upper().strip()
        if not code:
            continue
        for index, (page, _text, drawing) in enumerate(page_info):
            if remaining[index].get(code, 0) <= 0:
                continue
            remaining[index][code] -= 1
            row["source_page"] = page.get("page_number")
            # The parent is the DRAWING the page is, not the page. A sheet with no readable
            # title block places the row without claiming an owner for it — the honest
            # outcome, and the one the compiler's refusal is built to expect.
            if drawing:
                row["bom_parent"] = drawing
            placed += 1
            break
    return placed


def summarise_document(pdf_path: Path, plumber_pages: List[Dict[str, Any]], pypdf_pages: List[str], vision_pages: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    joined_text = "\n\n".join(page["text"] for page in plumber_pages if page["text"])
    joined_title_block = "\n\n".join(page["region_text"]["title_block"] for page in plumber_pages if page["region_text"]["title_block"])
    joined_bom = "\n\n".join(
        normalize_text(f"{page['region_text']['bom']} {page['region_text']['notes']}")
        for page in plumber_pages
        if page["region_text"]["bom"] or page["region_text"]["notes"]
    )
    joined_notes = "\n\n".join(page["region_text"]["notes"] for page in plumber_pages if page["region_text"]["notes"])

    document_analysis = build_textual_manufacturing_summary(
        joined_text,
        title_block_text=joined_title_block,
        bom_text=joined_bom,
        notes_text=joined_notes,
        page_role_hint="document",
    )

    # WHERE EACH ROW CAME FROM, recorded at the only point it is still knowable.
    _placed = attribute_bom_rows_to_source_pages(
        document_analysis.get("bom_rows") or [], plumber_pages)
    _rows_total = len(document_analysis.get("bom_rows") or [])
    if _rows_total:
        _owned = sum(1 for r in document_analysis["bom_rows"] if r.get("bom_parent"))
        # A GATE NOBODY ASKS REPORTS NOTHING. If attribution places nothing, or places rows
        # without ever finding a drawing number, the hierarchy that depends on it will be
        # silently absent — and that is exactly how this defect survived to a customer price.
        print(f"   [bom] {_placed}/{_rows_total} row(s) traced to a sheet; "
              f"{_owned} carry the drawing that owns them"
              + ("" if _owned else " — no title block on any BOM page named a drawing, so "
                                   "these rows state no hierarchy"), flush=True)

    tb = document_analysis.get("title_block") or {}
    for field in ("colours", "surface_finishes"):
        if field in tb:
            tb[field] = _clean_field_list(tb[field], field)

    summary: Dict[str, Any] = {
        "source_file": pdf_path.name,
        "full_path": str(pdf_path),
        "page_count": len(plumber_pages),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_metadata": extract_pdf_metadata(pdf_path),
        "detected_labels": find_labels(joined_title_block or joined_text),
        "pattern_summary": extract_patterns(joined_text),
        "document_analysis": document_analysis,
        "output_targets": {
            "json_dir": str(config.JSON_DIR),
            "log_dir": str(config.LOG_DIR),
            "text_dir": str(config.TEXT_DIR),
            "csv_dir": str(config.CSV_DIR),
            "sql_dir": str(config.SQL_DIR),
            "page_images_dir": str(config.PAGE_IMAGES_DIR),
        },
        "pages": [],
        "manual_review_items": [],
    }
    vision_lookup = {item.get("page_number"): item for item in (vision_pages or [])}

    for page in plumber_pages:
        page_text = page["text"]
        page_number = page["page_number"]
        title_block_source = page["region_text"]["title_block"] if page["title_block_calibration"]["use_region_text"] else page_text
        page_analysis = build_textual_manufacturing_summary(
            page_text,
            title_block_text=title_block_source,
            bom_text=normalize_text(f"{page['region_text']['bom']} {page['region_text']['notes']}"),
            notes_text=page["region_text"]["notes"],
            page_role_hint=page["page_role"]["primary_role"],
        )
        vision_page = vision_lookup.get(page_number)
        llm_page = reconcile_with_llm(
            {
                "page_number": page_number,
                "page_role": page.get("page_role", {}),
                "deterministic_page_analysis": page_analysis,
                "vision_page": vision_page or {},
            }
        )
        pa_tb = page_analysis.get("title_block") or {}
        for field in ("colours", "surface_finishes"):
            if field in pa_tb:
                pa_tb[field] = _clean_field_list(pa_tb[field], field)
        page_stub = {
            "page_number": page_number,
            "page_role": page["page_role"],
            "region_text": page["region_text"],
            "pdfplumber_text": page_text,
            "page_analysis": page_analysis,
        }
        page_analysis = reconcile_page_analysis(page_stub, vision_page=vision_page, llm_page=llm_page)
        summary["pages"].append(
            {
                "page_number": page_number,
                "source_pdf_path": str(pdf_path.resolve()),
                "pdfplumber_text": page_text,
                "normalized_text": page["normalized_text"],
                "pypdf_text": pypdf_pages[page_number - 1] if page_number - 1 < len(pypdf_pages) else "",
                "word_count": page["word_count"],
                "page_width": page["page_width"],
                "page_height": page["page_height"],
                "layout_regions": page["layout_regions"],
                "region_text": page["region_text"],
                "page_role": page["page_role"],
                "title_block_calibration": page["title_block_calibration"],
                "labels_found": find_labels(page["region_text"]["title_block"] or page_text),
                "pattern_summary": extract_patterns(page_text),
                "page_analysis": page_analysis,
                "text_preview": page_text[:1000],
                "vision_extraction": vision_page or {},
            }
        )
        if page_analysis.get("review_flags"):
            summary["manual_review_items"].append(
                {
                    "page_number": page_number,
                    "issues": page_analysis["review_flags"],
                    "confidence": page_analysis.get("confidence", {}),
                }
            )

    return summary


def _write_primary_outputs(
    summary: Dict[str, Any],
    json_path: Path,
    text_path: Path,
    log_path: Path,
    csv_path: Path,
    sql_path: Path,
    variance_xlsx_path: Path,
    variance_csv_path: Path,
    variance_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []

    try:
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        failures.append({"stage": "write_json", "error": str(exc)})

    try:
        with text_path.open("w", encoding="utf-8") as handle:
            handle.write(f"SOURCE FILE: {summary['source_file']}\n")
            handle.write(f"PAGE COUNT: {summary['page_count']}\n")
            handle.write(f"DETECTED LABELS: {', '.join(summary['detected_labels'])}\n")
            handle.write(f"PART NUMBERS: {', '.join(summary['pattern_summary']['part_numbers'])}\n")
            handle.write(f"DATES: {', '.join(summary['pattern_summary']['dates'])}\n\n")
            handle.write("=" * 80 + "\nDOCUMENT ANALYSIS\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("document_analysis", {}), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            handle.write("=" * 80 + "\nMANUFACTURING WRITE-UP\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("manufacturing_writeup", {}), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            handle.write("=" * 80 + "\nVALIDATION\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("manufacturing_writeup", {}).get("validation", {}), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            handle.write("=" * 80 + "\nMANUAL REVIEW\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("manual_review_items", []), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            handle.write("=" * 80 + "\nESTIMATE SOURCE EXTRACT (workbook + database + config)\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("estimate_source_extract", {}), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            handle.write("=" * 80 + "\nESTIMATE SUMMARY\n" + "=" * 80 + "\n")
            handle.write(json.dumps(summary.get("estimate_summary", {}), indent=2, ensure_ascii=False, default=_json_default))
            handle.write("\n\n")
            for page in summary["pages"]:
                handle.write("=" * 80 + "\n")
                handle.write(f"PAGE {page['page_number']}\n")
                handle.write("=" * 80 + "\n")
                handle.write("ROLE: " + page.get("page_role", {}).get("primary_role", "unknown") + "\n")
                handle.write("TITLE BLOCK CALIBRATION: " + json.dumps(page.get("title_block_calibration", {}), ensure_ascii=False, default=_json_default) + "\n")
                handle.write("LABELS FOUND: " + ", ".join(page["labels_found"]) + "\n")
                handle.write("PATTERNS: " + json.dumps(page["pattern_summary"], ensure_ascii=False, default=_json_default) + "\n")
                handle.write("REGIONS: " + json.dumps(page.get("region_text", {}), ensure_ascii=False, default=_json_default) + "\n")
                handle.write("PAGE ANALYSIS: " + json.dumps(page.get("page_analysis", {}), ensure_ascii=False, default=_json_default) + "\n")
                handle.write("GEOMETRY: " + json.dumps(page.get("geometry_summary", {}), ensure_ascii=False, default=_json_default) + "\n\n")
                handle.write(page["pdfplumber_text"] or "[NO TEXT EXTRACTED]")
                handle.write("\n\n")
    except Exception as exc:
        failures.append({"stage": "write_text", "error": str(exc)})

    try:
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "source_file": summary["source_file"],
                        "page_count": summary["page_count"],
                        "scanned_at": summary["scanned_at"],
                        "detected_labels": summary["detected_labels"],
                        "part_numbers": summary["pattern_summary"]["part_numbers"],
                        "validation_status": summary.get("manufacturing_writeup", {}).get("validation", {}).get("status"),
                        "output_csv": str(csv_path),
                    },
                    indent=2,
                    default=_json_default,
                )
            )
    except Exception as exc:
        failures.append({"stage": "write_log", "error": str(exc)})

    try:
        rows = build_estimate_input_rows(summary)
        append_rows_to_csv(csv_path, rows)
    except Exception as exc:
        failures.append({"stage": "write_csv", "error": str(exc)})

    try:
        from openpyxl import Workbook  # type: ignore

        workbook = Workbook()
        ws = workbook.active
        ws.title = "pricing_variance"
        headers = [
            "run_uuid",
            "source_file_name",
            "part_number",
            "comparison_scope",
            "metric_name",
            "manual_value",
            "ai_value",
            "abs_variance",
            "pct_variance",
            "status",
            "notes",
            "manual_source",
            "ai_source",
        ]
        ws.append(headers)
        for row in variance_rows:
            ws.append([row.get(header) for header in headers])
        workbook.save(variance_xlsx_path)
    except Exception:
        try:
            import csv
            with variance_csv_path.open("w", newline="", encoding="utf-8") as handle:
                headers = [
                    "run_uuid",
                    "source_file_name",
                    "part_number",
                    "comparison_scope",
                    "metric_name",
                    "manual_value",
                    "ai_value",
                    "abs_variance",
                    "pct_variance",
                    "status",
                    "notes",
                    "manual_source",
                    "ai_source",
                ]
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerows(variance_rows)
        except Exception as exc:
            failures.append({"stage": "write_variance", "error": str(exc)})

    try:
        write_postgres_insert_sql(summary, sql_path)
    except Exception as exc:
        failures.append({"stage": "write_sql", "error": str(exc)})

    return failures


def _write_archive_copies(
    summary: Dict[str, Any],
    archive_json_path: Path,
    archive_text_path: Path,
    archive_log_path: Path,
    archive_csv_path: Path,
    archive_sql_path: Path,
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    saved = summary.get("saved_output_paths", {})
    copy_pairs = [
        (Path(saved.get("json", "")), archive_json_path, "archive_json"),
        (Path(saved.get("text", "")), archive_text_path, "archive_text"),
        (Path(saved.get("log", "")), archive_log_path, "archive_log"),
        (Path(saved.get("sql", "")), archive_sql_path, "archive_sql"),
    ]
    for src, dst, stage in copy_pairs:
        try:
            if src.exists():
                shutil.copy2(src, dst)
        except Exception as exc:
            failures.append({"stage": stage, "error": str(exc)})

    try:
        build_rows = build_estimate_input_rows(summary)
        if build_rows:
            import csv
            with archive_csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=config.CSV_HEADERS)
                writer.writeheader()
                writer.writerows(build_rows)
    except Exception as exc:
        failures.append({"stage": "archive_csv", "error": str(exc)})
    return failures


def write_outputs(summary: Dict[str, Any]) -> Tuple[Path, Path, Path, Path]:
    metadata = build_run_metadata(summary)
    stem = str(summary.get("job_output_stem") or Path(summary["source_file"]).stem)
    version_label = metadata["source_file_version_label"]
    timestamp = summary.get("scanned_at", datetime.now().isoformat(timespec="seconds")).replace(":", "-").replace("T", "_")
    json_path = config.JSON_DIR / f"{stem}.json"
    text_path = config.TEXT_DIR / f"{stem}.txt"
    log_path = config.LOG_DIR / f"{stem}.log"
    csv_path = config.CSV_DIR / "part_estimate_inputs.csv"
    sql_path = config.SQL_DIR / f"{stem}.sql"
    variance_xlsx_path = config.CSV_DIR / f"{stem}_pricing_variance.xlsx"
    variance_csv_path = config.CSV_DIR / f"{stem}_pricing_variance.csv"
    archive_json_path = config.ARCHIVE_JSON_DIR / f"{stem}_{version_label}_{timestamp}.json"
    archive_text_path = config.ARCHIVE_TEXT_DIR / f"{stem}_{version_label}_{timestamp}.txt"
    archive_log_path = config.ARCHIVE_LOG_DIR / f"{stem}_{version_label}_{timestamp}.log"
    archive_csv_path = config.ARCHIVE_CSV_DIR / f"{stem}_{version_label}_{timestamp}.csv"
    archive_sql_path = config.ARCHIVE_SQL_DIR / f"{stem}_{version_label}_{timestamp}.sql"

    summary["saved_output_paths"] = {
        "json": str(json_path),
        "text": str(text_path),
        "log": str(log_path),
        "csv": str(csv_path),
        "sql": str(sql_path),
        "pricing_variance_xlsx": str(variance_xlsx_path),
        "pricing_variance_csv": str(variance_csv_path),
    }
    summary["archived_output_paths"] = {
        "json": str(archive_json_path),
        "text": str(archive_text_path),
        "log": str(archive_log_path),
        "csv": str(archive_csv_path),
        "sql": str(archive_sql_path),
    }
    variance_rows = build_pricing_variance_rows(summary)
    summary["pricing_variance_rows"] = variance_rows
    write_failures = _write_primary_outputs(
        summary,
        json_path,
        text_path,
        log_path,
        csv_path,
        sql_path,
        variance_xlsx_path,
        variance_csv_path,
        variance_rows,
    )
    archive_failures = _write_archive_copies(
        summary,
        archive_json_path,
        archive_text_path,
        archive_log_path,
        archive_csv_path,
        archive_sql_path,
    )
    summary["output_write_failures"] = write_failures + archive_failures
    return json_path, text_path, log_path, csv_path


def _inherit_document_material_to_parts(
    parts: List[Dict[str, Any]],
    document_analysis: Dict[str, Any],
) -> None:
    """
    Propagate document-level material to parts that have no material of their own.
    GA/assembly drawings state material once in the title block, not per BOM row.
    """
    if not parts:
        return
    pf = document_analysis.get("primary_fields") or {}
    doc_mat_norm = (
        pf.get("normalized_material_majority")
        or pf.get("normalized_material")
        or None
    )
    tb_norm = (document_analysis.get("title_block") or {}).get("normalized") or {}
    doc_mat_raw = tb_norm.get("primary_material") or None
    if not doc_mat_norm and not doc_mat_raw:
        return
    for part in parts:
        # Display boards (VINYL-* / DISPLAY BOARD) must NOT inherit the assembly's
        # document-level material (typically MILD STEEL). They are printed boards,
        # costed by the display-board recogniser. Skip inheritance for them.
        # NOTE: do not key on "GRAPHIC" — "GRAPHIC CHANNEL" parts are real steel.
        _pn_u = str(part.get("part_number") or "").upper()
        _desc_u = str(part.get("description") or "").upper()
        if _pn_u.startswith("VINYL-") or "DISPLAY BOARD" in _desc_u:
            continue
        existing = str(part.get("normalized_material") or "").strip()
        if existing and existing not in ("?", "", "None", "UNKNOWN"):
            continue
        if part.get("materials"):
            continue
        if doc_mat_norm:
            # INHERITED from the document, not read from this part. Rank 60: better than a
            # guess, weaker than anything that looked at the part itself. The `if
            # part.get("materials"): continue` guard above protects a part that states its
            # own material, but says nothing about a part whose material came from the MODEL.
            _apply_field(part, "normalized_material", doc_mat_norm, "bom_tree")
            part.setdefault("material_inherited_from", "document_level")
        if doc_mat_raw and not part.get("materials"):
            part["materials"] = [doc_mat_raw]
            part.setdefault("material_inherited_from", "document_level")


def _fill_part_revisions_from_pages(summary: Dict[str, Any]) -> None:
    """Populate each part's revision from its OWN drawing's title block.

    Must run BEFORE DXF matching so the matcher's revision-aware flat selection
    (_pick_best_flat: +3 for a matching rev letter) can fire. Without this the part
    reaches the matcher with revision=None and a stale/older DXF variant in the folder
    can win over the correct current-revision flat (1282 base plate: the 0-bend "500mm"
    DXF bound instead of the 6-bend "REV A" flat).

    Reads the revision from each part's own source pages, never another drawing's, by
    matching the title-block "DWG NO ... <part-number> <REV>" pattern in that page's
    text. Only fills when the part has no revision; never overwrites.
    """
    mw = summary.get("manufacturing_writeup") or {}
    parts = mw.get("parts") or []
    pages = summary.get("pages") or []
    if not parts or not pages:
        return

    # page_number -> page text (prefer pdfplumber text, fall back to normalized)
    page_text_by_num: Dict[int, str] = {}
    for pg in pages:
        try:
            num = int(pg.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if num:
            page_text_by_num[num] = str(
                pg.get("pdfplumber_text") or pg.get("normalized_text") or ""
            )

    def _rev_for_part(part: Dict[str, Any]) -> Optional[str]:
        pn = str(part.get("part_number") or "").strip()
        if not pn:
            return None
        # Build a tolerant pattern: the title block reads e.g. "... 1450-01C A"
        # The part number may carry a trailing letter; the revision is a single
        # standalone capital following the part number (allow trailing '-').
        pn_pat = re.escape(pn).replace(r"\-", r"[\s\-]*")
        rev_re = re.compile(pn_pat + r"\s*[\-]?\s*([A-Z])\b")
        for pgnum in (part.get("pages") or []):
            try:
                txt = page_text_by_num.get(int(pgnum), "")
            except (TypeError, ValueError):
                continue
            if not txt:
                continue
            m = rev_re.search(txt)
            if m:
                return m.group(1).upper()
        return None

    for part in parts:
        existing = str(part.get("revision") or part.get("drawing_revision") or "").strip()
        if existing and existing not in ("?", "", "None", "UNKNOWN"):
            continue
        rev = _rev_for_part(part)
        if rev:
            part["revision"] = rev
            part.setdefault("revision_inherited_from", "page_title_block")
            print(f"   [revision] {part.get('part_number')} revision -> {rev}", flush=True)


def _build_additive_summary_sections(summary: Dict[str, Any]) -> None:
    manufacturing_writeup = summary.get("manufacturing_writeup", {})
    estimate_summary = summary.get("estimate_summary", {})
    document_analysis = summary.get("document_analysis", {})
    parts = manufacturing_writeup.get("parts", [])

    _inherit_document_material_to_parts(parts, document_analysis)

    summary["drawing_metadata"] = {
        "source_file": summary.get("source_file"),
        "full_path": summary.get("full_path"),
        "page_count": summary.get("page_count"),
        "scanned_at": summary.get("scanned_at"),
        "pdf_metadata": summary.get("pdf_metadata", {}),
        "document_analysis": document_analysis,
        "run_metadata": summary.get("run_metadata", {}),
    }
    summary["assembly_summary"] = {
        "document_overview": manufacturing_writeup.get("document_overview", {}),
        "validation": manufacturing_writeup.get("validation", {}),
        "assembly_relations": manufacturing_writeup.get("assembly_relations", {}),
        "manufacturing_observations": manufacturing_writeup.get("manufacturing_observations", []),
    }
    summary["parts"] = parts
    summary["cost_breakdown"] = estimate_summary.get("cost_breakdown", {})
    summary["estimate_source_extract"] = estimate_summary.get("estimate_source_extract", {})
    estimate_risk_flags = {
        flag
        for est_part in estimate_summary.get("part_estimates", [])
        for flag in est_part.get("risk_flags", [])
    }
    summary["risk_flags"] = sorted(
        {
            flag
            for part in parts
            for flag in part.get("risk_flags", [])
        }
        | estimate_risk_flags
    )
    summary["nesting_recommendations"] = {
        "part_recommendations": [
            {
                "part_number": part.get("part_number"),
                "requires_flat_blank": part.get("manufacturing_interpretation", {}).get("requires_flat_blank"),
                "nesting_class": part.get("normalized_geometry", {}).get("nesting_class"),
                "blank_area_m2": part.get("normalized_geometry", {}).get("blank_area_m2"),
            }
            for part in parts
        ]
    }
    summary["alternative_processes"] = []


def scan_file(
    drawing_path: Path,
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    if is_dxf_path(drawing_path):
        return scan_dxf_file(
            drawing_path,
            attach_dxf_paths=attach_dxf_paths,
            auto_discover_dxf=auto_discover_dxf,
        )
    return scan_pdf_file(
        drawing_path,
        attach_dxf_paths=attach_dxf_paths,
        auto_discover_dxf=auto_discover_dxf,
    )


def scan_dxf_file(
    dxf_path: Path,
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    started = time.time()

    def _debug(stage: str) -> None:
        if debug:
            elapsed = round(time.time() - started, 2)
            print(f"[DEBUG] {stage} (+{elapsed}s)")

    print("   -> DXF source: exact model-space geometry (ezdxf)")
    _debug("start extract_dxf_pages")
    plumber_pages = extract_dxf_pages(dxf_path)
    _debug("done extract_dxf_pages")

    _debug("start summarise_document")
    summary = summarise_document(dxf_path, plumber_pages, [""], vision_pages=[])
    summary["source_format"] = "dxf"
    summary["pdf_metadata"] = extract_dxf_metadata(dxf_path)
    _debug("done summarise_document")

    processed_pages = summary.get("pages", [])
    for page in processed_pages:
        page["source_dxf_path"] = str(dxf_path.resolve())

    _debug("start analyse_dxf_document_geometry")
    geometry_results = analyse_dxf_document_geometry(processed_pages, dxf_path)
    for i, page in enumerate(processed_pages):
        if i < len(geometry_results.get("pages", [])):
            page["geometry"] = geometry_results["pages"][i].get("geometry", {})
            page["calibration"] = geometry_results["pages"][i].get("calibration", {})
    geometry_summary = {
        "document_geometry_reliability": geometry_results.get("document_geometry_reliability", 0.0),
        "overall_confidence": geometry_results.get("overall_confidence", 0.0),
        "pages": geometry_results.get("pages", []),
        "fitz_available": False,
        "pdf_path_recovered": False,
        "dxf_path": geometry_results.get("dxf_path"),
        "pages_with_dxf_geometry": geometry_results.get("pages_with_dxf_geometry", 0),
        "notes": "DXF model-space geometry via ezdxf (native mm)",
        "source": "dxf",
    }
    summary["geometry_summary"] = geometry_summary
    print(
        f"   -> Geometry reliability: {geometry_results.get('document_geometry_reliability', 0.0):.2f} "
        f"(DXF native units)"
    )
    _debug("done analyse_dxf_document_geometry")
    return _finalize_scan_summary(
        summary,
        started,
        debug,
        geometry_summary=geometry_summary,
        attach_dxf_paths=attach_dxf_paths,
        auto_discover_dxf=auto_discover_dxf,
    )


def scan_pdf_file(
    pdf_path: Path,
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    started = time.time()

    def _debug(stage: str) -> None:
        if debug:
            elapsed = round(time.time() - started, 2)
            print(f"[DEBUG] {stage} (+{elapsed}s)")

    _debug("start extract_pdf_summary")
    summary = extract_pdf_summary(pdf_path)
    geometry_summary = summary.get("geometry_summary") or {}
    print(
        f"   -> Geometry reliability: {geometry_summary.get('document_geometry_reliability', 0.0):.2f} "
        f"(target >0.75)"
    )
    print(
        f"   -> Fitz vector pages: {int(geometry_summary.get('pages_with_fitz_drawings', 0) or 0)}/"
        f"{len(summary.get('pages') or [])}  "
        f"PDF path recovered: {bool(geometry_summary.get('pdf_path_recovered'))}"
    )
    _debug("done extract_pdf_summary")
    return _finalize_scan_summary(
        summary,
        started,
        debug,
        geometry_summary=geometry_summary,
        pdf_path=pdf_path,
        attach_dxf_paths=attach_dxf_paths,
        auto_discover_dxf=auto_discover_dxf,
    )


def _finalize_scan_summary(
    summary: Dict[str, Any],
    started: float,
    debug: bool,
    geometry_summary: Dict[str, Any] | None = None,
    *,
    pdf_path: Path | None = None,
    job_folder: Path | None = None,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    def _debug(stage: str) -> None:
        if debug:
            elapsed = round(time.time() - started, 2)
            print(f"[DEBUG] {stage} (+{elapsed}s)")

    geom_pages = (geometry_summary or summary.get("geometry_summary") or {}).get("pages", [])
    _debug("start merge_page_analysis")
    summary = merge_page_analysis(summary, geom_pages)
    _debug("done merge_page_analysis")

    # -- Dual-path BOM read (default ON) ---------------------------------------
    # The deterministic (pdfplumber word-geometry) + vision (Grok) reconciled reader is
    # the authoritative source of the bom_rows that build_document_writeup consumes
    # below. It reads the parts list the drawing PRINTS; the fallback reconstructs one
    # from scrambled text. SDI_DUALPATH_BOM=0 restores the fallback for comparison.
    # Any failure leaves the existing rows untouched (a scan never breaks on this).
    from bom_pipeline import dual_path_enabled as _dual_path_enabled
    if _dual_path_enabled():
        try:
            from bom_pipeline import reconciled_bom_rows_for_job
            # Prefer the EXACT PDF paths the pipeline already scanned (job_source_pdfs)
            # over re-discovering them from the folder. find_pdfs(folder) returned []
            # here on the UNC share (pdfs_found=0) even though the pipeline read the PDF
            # fine — re-globbing the folder is a needless second point of failure. These
            # resolved paths are known-good, so Path A reads the same files the estimate
            # was built from.
            _job_pdfs = [j.get("path") for j in (summary.get("job_source_pdfs") or []) if j.get("path")]
            # DIAGNOSTIC (temporary): show which reconcile input branch is taken and why,
            # so an empty _dp is explainable at the source (job_source_pdfs vs folder vs
            # single pdf). Prints the actual paths so a bad/absent path is visible.
            print(f"   [recon-input] job_source_pdfs={len(_job_pdfs)} "
                  f"job_folder={str(job_folder)!r} scan_mode={summary.get('scan_mode')!r} "
                  f"pdf_path={str(pdf_path)!r}", flush=True)
            if _job_pdfs:
                print(f"   [recon-input] using job_source_pdfs -> {_job_pdfs}", flush=True)
                _dp = reconciled_bom_rows_for_job(pdfs=_job_pdfs)
            elif job_folder and summary.get("scan_mode") == "folder_as_job":
                print(f"   [recon-input] fallback to folder discovery on {str(job_folder)!r}", flush=True)
                _dp = reconciled_bom_rows_for_job(folder=job_folder)
            elif pdf_path:
                _dp = reconciled_bom_rows_for_job(pdfs=[pdf_path])
            else:
                _fp_src = summary.get("full_path") or summary.get("source_file")
                _dp = reconciled_bom_rows_for_job(pdfs=[_fp_src]) if _fp_src else {"rows": []}
            print(f"   [recon-input] _dp keys={sorted((_dp or {}).keys())} "
                  f"pdf_paths={len((_dp or {}).get('pdf_paths') or [])} "
                  f"a_count={(_dp or {}).get('a_count')} b_count={(_dp or {}).get('b_count')}", flush=True)
            _da = summary.setdefault("document_analysis", {})
            # Recorded whether or not rows came back. Which readers covered this job is
            # the one fact that cannot be recovered from the rows themselves — an absent
            # reader leaves no trace in what it did not find — and check_both_bom_readers_ran
            # reads it. Written BEFORE the rows guard so a job the readers could not read
            # at all still says who was unable to read it.
            _da["bom_readers_unread"] = list(_dp.get("unread") or [])
            _da["bom_vision_calls"] = dict(_dp.get("vision_calls") or {})
            _vc = _da["bom_vision_calls"]
            if _vc:
                print(f"   [bom-vision] {_vc.get('paid', 0)} page(s) sent to the model, "
                      f"{_vc.get('cached', 0)} from cache, "
                      f"{_vc.get('skipped', 0)} not selected", flush=True)
            if _dp.get("rows"):
                _da["bom_rows"] = _dp["rows"]
                _da["bom_code_quality_findings"] = _dp.get("findings", [])
                _debug(f"dual-path bom_rows applied: {len(_dp['rows'])} rows")
        except Exception as _dp_err:
            _debug(f"dual-path bom_rows hook skipped: {_dp_err}")

        # -- Dual-path -> part_estimates reconciliation (self-contained) -----------
        # bom_rows was updated above, but the SHEET reads estimate_summary.part_estimates.
        # Push dual-path fastener quantities/identities into part_estimates so they reach
        # the sheet. Failure-isolated; fabricated parts never touched.
        try:
            if False and _dp.get("rows"):  # SUPERSEDED: reconcile moved to AFTER estimate_document (see _reconcile_dualpath_into_part_estimates). This early copy always skipped — part_estimates did not exist yet.
                import estimator as _E_recon
                import re as _re_recon

                _es_recon = summary.setdefault("estimate_summary", {})
                _parts_recon = _es_recon.get("part_estimates")
                if _parts_recon is None:
                    _parts_recon = summary.get("part_estimates")

                if isinstance(_parts_recon, list):

                    def _is_fastener_row(_r):
                        _d = (str(_r.get("description") or "") + " " +
                              str(_r.get("part_code") or _r.get("code") or
                                  _r.get("part_number") or "")).upper()
                        return any(_k in _d for _k in ("CLINCH", "NUT", "KNURL", "KNOB",
                                   "THUMB", "SCREW", "PEM", "STUD", "RIVET", "THUM",
                                   "WASHER", "BOLT", "GLIDE"))

                    def _dp_code(_r):
                        return str(_r.get("part_code") or _r.get("code") or
                                   _r.get("part_number") or "").strip()

                    def _dp_qty(_r):
                        _q = _r.get("qty") or _r.get("quantity") or _r.get("qty_per_unit")
                        try:
                            return int(float(_q)) if _q is not None else None
                        except (TypeError, ValueError):
                            return None

                    def _p_code(_p):
                        return str(_p.get("part_number") or "").strip().upper()

                    def _clean_code(_desc, _fallback):
                        # THE THIRD COPY OF THIS TABLE, and the reason the rule is now in one
                        # module: three readers minting hardware codes from three private
                        # copies, at three different points in the run.
                        from part_identity import synthesise_bought_in_code
                        return (synthesise_bought_in_code(_desc, _fallback)
                                or _fallback or "BI-FIXING")

                    _added = _updated = 0
                    for _r in _dp["rows"]:
                        if not _is_fastener_row(_r):
                            continue
                        _code = _dp_code(_r)
                        _qty = _dp_qty(_r)
                        _desc = str(_r.get("description") or _code)
                        if _qty is None or _qty <= 0:
                            _qty = 1

                        # 1) CODE match -> update qty, no add
                        _cm = None
                        if _code:
                            for _p in _parts_recon:
                                if _p_code(_p) == _code.upper():
                                    _cm = _p
                                    break
                        if _cm is not None:
                            if _cm.get("quantity") != _qty:
                                if _apply_field(_cm, "quantity", _qty, "bom_tree"):
                                    _cm.setdefault("review_flags", []).append(
                                        f"Quantity set to {_qty} from dual-path BOM table read")
                                _updated += 1
                            continue

                        # 2) TOKEN match vs bought-in parts -> dual-path qty wins
                        _ctoks = _E_recon._bought_in_token_set({"description": _desc})
                        _tm = None
                        if _ctoks is not None:
                            for _p in _parts_recon:
                                _roles = _p.get("page_roles") or []
                                if not ("bought_in" in _roles or _p_code(_p).startswith("BI-")):
                                    continue
                                _ptoks = _E_recon._bought_in_token_set(_p)
                                if _ptoks is not None and _E_recon._bought_in_same_item(_ctoks, _ptoks):
                                    _tm = _p
                                    break
                        if _tm is not None:
                            if _tm.get("quantity") != _qty:
                                _old = _tm.get("quantity")
                                _apply_field(_tm, "quantity", _qty, "bom_tree")
                                _tm.setdefault("review_flags", []).append(
                                    f"Quantity corrected {_old} -> {_qty} from dual-path BOM "
                                    f"table read (matched '{_desc}')")
                                _updated += 1
                            continue

                        # 3) No match -> ADD clean bought-in row
                        _cc = _clean_code(_desc, _code)
                        if any(_p_code(_p) == _cc.upper() for _p in _parts_recon):
                            continue
                        _parts_recon.append({
                            "part_number": _cc, "description": _desc, "quantity": _qty,
                            "pages": [], "page_roles": ["bought_in"], "materials": [],
                            "surface_finishes": [], "colours": [], "thicknesses_mm": [],
                            "weights": [], "textual_operations": ["handling"],
                            "inferred_operations": [], "flat_pattern_detected": False,
                            "assembly_candidate": False, "process_notes": [],
                            "review_flags": [
                                f"Added from dual-path BOM table read (code '{_code}' -> "
                                f"'{_cc}'), qty {_qty} - price via waterfall, estimator to verify"],
                            "confidence": {"overall": 0.0}, "source": "non_sdi_bom_row",
                        })
                        _added += 1

                    if _es_recon.get("part_estimates") is not None:
                        _es_recon["part_estimates"] = _parts_recon
                    else:
                        summary["part_estimates"] = _parts_recon
                    if _added or _updated:
                        print(f"   [dual-path recon] part_estimates: {_updated} qty-corrected, "
                              f"{_added} added from BOM table read")
        except Exception as _dpr_err:
            _debug(f"dual-path part_estimates reconcile skipped: {_dpr_err}")

    _debug("start build_document_writeup")
    summary["manufacturing_writeup"] = build_document_writeup(summary)
    _debug("done build_document_writeup")

    # Fill each part's revision from its own drawing's title block BEFORE DXF matching,
    # so revision-aware flat selection can prefer the current-revision DXF over stale variants.
    _fill_part_revisions_from_pages(summary)

    job_cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    discover = job_cfg.get("auto_discover_on_pdf_scan", True) if auto_discover_dxf is None else bool(auto_discover_dxf)
    source_pdf = pdf_path or Path(summary.get("full_path") or summary.get("source_file") or "")
    dxf_paths: List[Path] = []
    if job_folder and summary.get("scan_mode") == "folder_as_job":
        dxf_paths = collect_dxf_paths_for_job(
            Path(job_folder),
            summary,
            attach_dxf_paths=attach_dxf_paths,
            auto_discover_dxf=discover,
        )
    elif source_pdf and str(source_pdf).lower().endswith(".pdf"):
        dxf_paths = collect_dxf_paths_for_pdf_scan(
            Path(source_pdf),
            summary,
            attach_dxf_paths=attach_dxf_paths,
            auto_discover_dxf=discover,
        )
    elif attach_dxf_paths:
        dxf_paths = collect_dxf_paths_for_pdf_scan(
            Path(summary.get("full_path") or "."),
            summary,
            attach_dxf_paths=attach_dxf_paths,
            auto_discover_dxf=False,
        )

    if dxf_paths:
        print(f"   -> Augmenting {len(dxf_paths)} flat DXF file(s) into PDF parts...")
        for dxf_path in dxf_paths:
            print(f"      + {dxf_path.name}")
        _debug("start augment_summary_with_dxf")
        summary = augment_summary_with_dxf(summary, dxf_paths, reestimate=False)
        _debug("done augment_summary_with_dxf")

    # ── Pre-estimate normalisation ────────────────────────────────────────────
    # Must run BEFORE estimate_document so BOUGHT_IN materials price at £0,
    # and boilerplate-sourced operations are stripped before routing is costed.
    _pre_estimate_parts = summary.get("manufacturing_writeup", {}).get("parts") or []
    if _pre_estimate_parts:
        from json_normaliser import normalise_material_for_part, _strip_spec_boilerplate, infer_operations
        # Junk part descriptions from title block — filter before normalisation
        _JUNK_DESC_PATTERNS = re.compile(
            r"^[\.\s]*BY[\.\s]*$"              # ". BY." / "BY."
            r"|^DRAWN\s+BY"                    # "DRAWN BY"
            r"|^CHECKED\s+BY"                  # "CHECKED BY"
            r"|^APPROVED\s+BY"                 # "APPROVED BY"
            r"|^DATE[\.\s]*$"                  # "DATE."
            r"|^REV(ISION)?[\.\s]*$"           # "REV." / "REVISION"
            r"|^SCALE[\s:]"                    # "SCALE:"
            r"|^SHEET\s+\d+"                   # "SHEET 1 OF"
            r"|GENERAL\s*TOLERANCES?"          # "GENERAL TOLERANCES: FINISH SPE..."
            r"|FINISH\s*SPEC(IFICATION)?"      # "FINISH SPECIFICATION"
            r"|^G\s*E\s*N\s*E\s*R\s*A\s*L"     # Spaced-out "G E N E R A L"
            r"|^\s*F\s*I\s*N\s*I\s*S\s*H"      # Spaced-out "F I N I S H"
            r"|SDI\s*DISPLAYS?\s*LTD"          # "SDI DISPLAYS LIMITED" in descriptions
            r"|^SURFACE\s+FINISH"              # "SURFACE FINISH:"
            r"|^MATERIAL\s*:?\s*$"             # bare "MATERIAL"
            r"|^UNLESS\s+OTHERWISE"            # "UNLESS OTHERWISE STATED"
            r"|^ALL\s+DIMS?\s+IN\s+MM"         # "ALL DIMS IN MM"
            r"|DO\s+NOT\s+SCALE",              # "DO NOT SCALE"
            re.IGNORECASE,
        )
        # Patterns that mean a "part number" is actually surface finish / boilerplate text
        _FAKE_PN_PATTERNS = re.compile(
            r"""
            ^(
                POWDER\s+COAT(ED)?               # "POWDER COATED"
                | SEMI[-\s]GLOSS                 # "SEMI-GLOSS"
                | COATED?\s*[-–]                 # "COATED -"
                | RAL\s*\d{4}                    # "RAL 9005"
                | GENERAL\s+TOLERANCES?          # "GENERAL TOLERANCES"
                | FINISH\s+SPEC                  # "FINISH SPEC"
                | SEE\s+ASSEMBLY                 # "SEE ASSEMBLY DRAWING"
                | CUSTOMER\s+SUPPLY              # "CUSTOMER SUPPLY"
                | DRAWN\s+BY                     # "DRAWN BY"
                | CHECKED\s+BY                   # "CHECKED BY"
                | APPROVED\s+BY                  # "APPROVED BY"
                | DATE[\s\.]*$                   # "DATE."
                | REV(ISION)?[\s\.]*$            # "REV." / "REVISION"
                | SCALE[\s:]+                    # "SCALE:"
                | SHEET[\s]+\d+                  # "SHEET 1"
            )
            """,
            re.IGNORECASE | re.VERBOSE,
        )

        def _is_valid_part_number(pn: str) -> bool:
            """
            Return True only if the string looks like a genuine SDI part number.
            Rejects surface finishes, boilerplate title-block text, RAL codes etc.
            """
            if not pn or not pn.strip():
                return False
            pn_stripped = pn.strip()
            if len(pn_stripped) < 3:
                return False
            if _FAKE_PN_PATTERNS.match(pn_stripped):
                return False
            # Real part numbers always have digits
            if not re.search(r'\d', pn_stripped):
                return False
            upper = pn_stripped.upper()
            _finish_words = ("COATED", "SEMI-GLOSS", "POWDER", "GLOSS", "MATT", "PRIMER")
            if any(w in upper for w in _finish_words):
                return False
            return True

        def _normalise_part_number(pn):
            """Strip, collapse spaces around dashes ('8172- 1' -> '8172-1'), upper-case."""
            if not pn:
                return pn
            pn = str(pn).strip()
            pn = re.sub(r'\s*-\s*', '-', pn)
            pn = re.sub(r'\s+', ' ', pn)
            return pn.upper()

        # Drop parts whose identity is pure title-block boilerplate.
        _pre_estimate_parts = [
            p for p in _pre_estimate_parts
            if not _JUNK_DESC_PATTERNS.match(
                str(p.get("description") or p.get("part_number") or "").strip()
            )
        ]
        # Normalise + validate each part_number: reject finish/boilerplate text.
        for _p in _pre_estimate_parts:
            _pn = _normalise_part_number(_p.get("part_number"))
            if _pn is not None:
                _p["part_number"] = _pn
            if _p.get("part_number") and not _is_valid_part_number(_p["part_number"]):
                _bad = _p["part_number"]
                _p["part_number"] = None
                _p.setdefault("review_flags", []).append({
                    "severity": "warning",
                    "flag": "invalid_part_number",
                    "detail": f"Rejected part_number '{_bad}' — looks like boilerplate/finish text",
                })
        # Write filtered list back so estimate_document() sees clean parts
        # Suppress stated_weight_g on assembly/overview pages to prevent
        # double-counting sub-part weights into parent assembly material cost.
        for _part in _pre_estimate_parts:
            _page_roles = _part.get("page_roles") or []
            _pages = _part.get("pages") or []
            _has_desc = bool(str(_part.get("description") or "").strip())
            _is_assembly_page = (
                "assembly" in str(_page_roles).lower()
                or (len(_pages) > 1 and not _has_desc)
                or not _has_desc
            )
            if _part.get("stated_weight_g") and _is_assembly_page:
                _part["stated_weight_g"] = None
                _part["weights"] = []

        # Strip year-values from dimension fields (e.g. date 07/04/2021 -> 2021mm)
        for _part in _pre_estimate_parts:
            for _dim_field in ('overall_length_mm', 'overall_width_mm'):
                _v = _part.get(_dim_field)
                if _v is not None and 1900.0 <= float(_v) <= 2100.0:
                    _part[_dim_field] = None   # precedence: direct-write ok — clears a dimension, adds no evidence
        summary.setdefault("manufacturing_writeup", {})["parts"] = _pre_estimate_parts

        # Drop None-PN BOM artefacts whose description is a qty-suffixed duplicate
        # of a named part (e.g. "OUTER TUBE 1" when 10777-01-01 is "OUTER TUBE").
        def _desc_core(d: Any) -> str:
            return re.sub(r"\s+\d+$", "", str(d or "").strip().upper())

        _named_cores = {
            _desc_core(p.get("description"))
            for p in _pre_estimate_parts if p.get("part_number")
        }
        _pre_estimate_parts = [
            p for p in _pre_estimate_parts
            if p.get("part_number") or _desc_core(p.get("description")) not in _named_cores
        ]

        # Deduplicate None-PN parts sharing page+geometry with a named part
        _by_geom: Dict[tuple, int] = {}
        _drop_idx: set = set()
        for _di, _pep in enumerate(_pre_estimate_parts):
            # NOTE: loop var is _pep (pre-estimate part), NOT _dp — _dp holds the
            # dual-path BOM result computed far above and consumed by the reconcile
            # after estimate_document. Reusing _dp here clobbered it, so the fastener
            # reconcile always saw a part dict (no "rows") and silently no-op'd.
            _gr = _pep.get("geometry_rollup") or _pep.get("geometry") or {}
            _cut = round(float(_gr.get("estimated_cut_length_mm") or 0))
            if _cut <= 0:
                continue
            _dk = (tuple(sorted(_pep.get("pages") or [])), _cut)
            if _dk not in _by_geom:
                _by_geom[_dk] = _di
                continue
            _prev_i = _by_geom[_dk]
            _prev_p = _pre_estimate_parts[_prev_i]
            if _pep.get("part_number") and not _prev_p.get("part_number"):
                _drop_idx.add(_prev_i)
                _by_geom[_dk] = _di
            elif not _pep.get("part_number") and _prev_p.get("part_number"):
                _drop_idx.add(_di)
            elif not _pep.get("part_number") and not _prev_p.get("part_number"):
                _drop_idx.add(_di)
        if _drop_idx:
            _pre_estimate_parts = [_p for _i, _p in enumerate(_pre_estimate_parts) if _i not in _drop_idx]
            summary.setdefault("manufacturing_writeup", {})["parts"] = _pre_estimate_parts

        for _part in _pre_estimate_parts:
            # DXF filename thickness — override tolerance-table noise (0.5/1.0/…)
            _dfn_thk = str(_part.get("dxf_source_file") or _part.get("geometry_source_path") or "")
            if _dfn_thk:
                _tm_thk = re.search(r"[_\-\s](\d+\.?\d*)\s*mm", _dfn_thk, re.IGNORECASE)
                if _tm_thk:
                    _tv_thk = float(_tm_thk.group(1))
                    if 0.3 <= _tv_thk <= 25.0:
                        # From the filename, so inference — not the geometry, not the model.
                        _apply_field(_part, "normalized_thickness_mm", _tv_thk, "inference")
            # 1. Set correct normalized_material (BOUGHT_IN, VENEERED_MDF etc.)
            _mat = normalise_material_for_part(_part)
            if _mat:
                _apply_field(_part, "normalized_material", _mat, "inference")
            # Fabricated MS flat patterns must not stay BOUGHT_IN (e.g. GRAPHIC CHANNEL).
            if (_part.get("normalized_material") or "").upper() == "BOUGHT_IN":
                _dfn_chk = str(_part.get("dxf_source_file") or _part.get("geometry_source_path") or "").upper()
                if _part.get("flat_pattern_detected") and ("_MS_" in _dfn_chk or " MS_" in _dfn_chk
                        or re.search(r"\d+\.?\d*\s*MM\s*MS", _dfn_chk)):
                    _apply_field(_part, "normalized_material", "MILD_STEEL", "inference")
            # DXF filename material fallback
            if not _part.get("normalized_material"):
                _dfn = str(_part.get("dxf_source_file") or _part.get("geometry_source_path") or "").upper()
                _dgs = str(_part.get("geometry_source") or "")
                if "dxf" in _dgs.lower() and _dfn:
                    if "_MS_" in _dfn or "MS_" in _dfn or "_MS." in _dfn:
                        _apply_field(_part, "normalized_material", "MILD_STEEL", "inference")
                    elif "PETG" in _dfn:
                        _apply_field(_part, "normalized_material", "ACRYLIC", "inference")
                    elif ("_ACR_" in _dfn or "ACRYLIC" in _dfn or "HI ACR" in _dfn
                            or "HI_ACR" in _dfn or "HIGH IMPACT" in _dfn or "HIGH_IMPACT" in _dfn
                            or "PERSPEX" in _dfn or "PMMA" in _dfn):
                        _apply_field(_part, "normalized_material", "ACRYLIC", "inference")
                    elif "JOINERY" in _dfn or "_MDF_" in _dfn:
                        _apply_field(_part, "normalized_material", "MDF", "inference")
                    elif "DISPA" in _dfn or "PAPER" in _dfn:
                        _apply_field(_part, "normalized_material", "BOUGHT_IN", "inference")
            # 2. Strip spec boilerplate from process_notes then re-derive ops
            _clean_notes = [_strip_spec_boilerplate(str(n)) for n in (_part.get("process_notes") or [])]
            _part["process_notes"] = _clean_notes
            # 3. Extract WEIGHT from PDF title block text -> feeds stated-weight
            #    material cost path in estimator (WEIGHT: 140.69g -> £0.11 steel)
            if not (_part.get("weights") and any(_part["weights"])):
                _all_page_text = " ".join(
                    str(
                        p.get("pdfplumber_text")
                        or p.get("text_preview")
                        or p.get("normalized_text")
                        or ""
                    )
                    for p in (summary.get("pages") or [])
                    if p.get("page_number") in (_part.get("pages") or [])
                )
                _weight_matches = re.findall(
                    r"WEIGHT\s*(?:\([^)]*\))?\s*[:\s]+([0-9]+(?:\.[0-9]+)?)\s*(KG|G)\b",
                    _all_page_text.upper(),
                )
                if _weight_matches:
                    # Take the largest weight found on the part's pages
                    _best = max(
                        (float(v) / 1000.0 if u == "G" else float(v) for v, u in _weight_matches),
                        default=None,
                    )
                    if _best and 0.001 <= _best <= 500.0:
                        _part["weights"] = [f"{round(_best * 1000, 2)}g"]
                        # Also set stated_weight_g for direct use in material costing
                        _part["stated_weight_g"] = round(_best * 1000, 2)
            # Important: infer only from free text notes, never from existing
            # operation codes (e.g. "welding") to avoid self-trigger loops.
            # Re-infer from clean notes and merge with existing upstream ops.
            # Do NOT replace entirely — upstream ops from document layout analysis
            # (e.g. "Weld and Dress" callouts) are legitimate and must be kept.
            _clean_text = _strip_spec_boilerplate(" ".join(_clean_notes))
            _clean_ops = set(infer_operations(_clean_text))
            _existing_ops = list(_part.get("textual_operations") or [])
            # Merge: start from clean inference, add any upstream ops not in result
            _merged = list(_clean_ops)
            for _op in _existing_ops:
                if _op not in _merged:
                    _merged.append(_op)
            # Finish-aware filter: remove ops physically impossible for this finish
            _finish_upper = " ".join(
                str(f) for f in (_part.get("surface_finishes") or [])
            ).upper()
            _raw_finishes = {"RAW", "BRIGHT DRAWN", "BRIGHT ZINC", "UNPAINTED"}
            _is_raw = any(r in _finish_upper for r in _raw_finishes)
            if _is_raw:
                _merged = [o for o in _merged if o not in
                           {"powder_coating", "diamond_polish", "wet_spray"}]
            _part["textual_operations"] = _merged
    # ─────────────────────────────────────────────────────────────────────────

    # ── SolidWorks native extract — LAYER 0 of the source waterfall ─────────────────────
    # Runs BEFORE the LLM extract and before costing, so modelled truth (flat blank from the
    # sheet-metal cut list, sheet gauge, applied material, full-depth BOM quantities) is in
    # the part records first and every lower source can only fill the gaps it leaves.
    #
    # Self-gating: it applies when the analyser's `_sw_native_extract.json` is present in the
    # job folder — i.e. when somebody ran tools/solidworks/sw_native_analyse.py on a machine
    # with SolidWorks. No file, no effect: the job runs on PDF + DXF exactly as before.
    #   SDI_APPLY_SOLIDWORKS=0   force off
    #   SDI_APPLY_SOLIDWORKS=1   force on (and say so loudly if the extract is missing)
    #   SDI_SW_EXTRACT_JSON=...  read the extract from an explicit path
    _sw_flag = os.getenv("SDI_APPLY_SOLIDWORKS", "").strip().lower()
    # BOUND BEFORE THE BRANCH, so every later reader gets a value rather than a name that
    # may or may not exist. The hierarchy pass 400 lines below fished this name out of the
    # frame's locals precisely because it could be unbound — and an unbound name and a
    # refused extract both arrived there as None, which made "the pass printed nothing"
    # unanswerable.
    # _sw_why records which of the several ways to have no extract actually happened.
    _sw_job = None
    _sw_why = "not attempted"
    if _sw_flag in {"0", "false", "no", "off"}:
        _sw_why = "SDI_APPLY_SOLIDWORKS is off"
    if _sw_flag not in {"0", "false", "no", "off"}:
        try:
            from source_connectors.solidworks import (
                apply_native_to_pre_estimate,
                native_extract_for_job,
            )
            _sw_json = os.getenv("SDI_SW_EXTRACT_JSON") or None
            # job_folder is only set on the folder-as-job path; a single --pdf scan passes
            # none. Fall back to the PDF's own directory, which is where the extract
            # naturally sits — otherwise the file is present and silently ignored.
            _sw_folder = job_folder or (Path(pdf_path).parent if pdf_path else None)
            # OPT-IN, NOT DEFAULT — and the reason is other people's work, not caution.
            # The analyser calls Dispatch("SldWorks.Application"), which ATTACHES to a
            # SolidWorks already running on this machine.
            #
            # THE DESTRUCTIVE HALF OF THIS IS FIXED, AND THIS COMMENT USED TO SAY OTHERWISE.
            # It described the analyser closing every title it touched, which stopped being
            # true when sw_native_analyse learned ownership: it asks what is already open
            # BEFORE opening anything, records those as borrowed, and close_all() closes only
            # the documents this process opened. A stale hazard note is not harmless — this
            # one was read as current and produced a warning telling somebody not to run a
            # tool that is now safe to run.
            #
            # WHAT REMAINS IS REAL AND DIFFERENT. A borrowed document is read in the state
            # the designer has it in, which may include unsaved changes — so the extract can
            # describe a model that is not what is on disk, and the freshness fingerprint
            # cannot see that. Save open work before extracting.
            #
            # Still opt-in HERE, because attaching to somebody's session mid-estimate is a
            # decision that belongs to whoever owns the machine, not to a costing run. Enable
            # it where SolidWorks belongs to this process — a dedicated worker or batch box —
            # with SDI_SW_RUN_ANALYSER=1. Everywhere else the pipeline consumes an extract
            # someone else produced, and says so loudly when models are present and no
            # extract is.
            _sw_run = os.getenv("SDI_SW_RUN_ANALYSER", "").strip().lower() \
                in {"1", "true", "yes", "on"}
            _sw_job = native_extract_for_job(folder=_sw_folder, json_path=_sw_json,
                                             run=_sw_run) \
                if (_sw_folder or _sw_json) else None
            if not (_sw_folder or _sw_json):
                _sw_why = ("no job folder and no SDI_SW_EXTRACT_JSON — nowhere to look for "
                           "an extract")
            elif _sw_job is None or not getattr(_sw_job, "found", False):
                _sw_why = (f"no readable _sw_native_extract.json under {_sw_folder} "
                           f"(run tools/solidworks/sw_native_analyse.py on the model folder)")
            else:
                _sw_why = ""
            if _sw_job is not None and _sw_job.meta.get("native_present_but_unread"):
                summary["solidworks_native"] = {
                    "source": "solidworks_api",
                    "found": False,
                    "native_files_present": _sw_job.meta.get("native_files_present"),
                    "native_present_but_unread": True,
                    "reason": _sw_job.meta.get("native_unread_reason"),
                    "analyser_error": _sw_job.meta.get("analyser_error"),
                }
                print(f"   [solidworks] {_sw_job.meta.get('native_files_present')} native model "
                      f"file(s) are in this job folder but were NOT read: "
                      f"{_sw_job.meta.get('native_unread_reason')}", flush=True)
            # ── AN EXTRACT FOR ANOTHER JOB IS WORSE THAN NO EXTRACT ──────────────
            # M&S 2085 was costed against 12120_sw_extract_v7.json — top assembly
            # 12120-01-GA, a different customer's job, bound through a persistent
            # SDI_SW_EXTRACT_JSON. The connector took it, matched nothing, applied
            # nothing, and stamped a native_extract_partial BLOCKER describing 12120's
            # unreadable model onto 2085's estimate. The estimator was told a released
            # component might be missing, about a pack with nothing to do with the job.
            #
            # Zeros are survivable. What this opens is not: SDI numbers sequentially, so
            # -01/-02/-03 collide across jobs constantly, and a colliding pair would have
            # had one job's bounding boxes, materials and bend counts written onto the
            # other's parts at the HIGHEST rank in the waterfall.
            _sw_id = None
            if _sw_job and _sw_job.found:
                from source_connectors.solidworks import extract_is_for_this_job
                _sw_id = extract_is_for_this_job(_pre_estimate_parts, _sw_job)
                if not _sw_id.get("belongs"):
                    # WHICH FAILURE IS THIS? Both look like zero matches, and for a whole
                    # session job 11350 reported "different job" while suffering "our matcher
                    # does not know this convention". Say which, and print the codes on both
                    # sides, so the next convention gap is one look rather than a week.
                    _ours = _sw_id.get("shares_job_number")
                    _why = ("THIS IS THIS JOB'S OWN EXTRACT and we could not match it — the "
                            "codes share a job number. That is a naming convention this "
                            "connector does not know, NOT a foreign pack."
                            if _ours else
                            "The codes share no job number with this one, so it describes a "
                            "different job. Point SDI_SW_EXTRACT_JSON at this job's extract, "
                            "or unset it.")
                    print(f"   [solidworks] REFUSED this extract. It describes "
                          f"{_sw_id.get('candidates')} part(s) under top assembly "
                          f"'{_sw_id.get('top_assembly') or '?'}' and matches NONE of this "
                          f"job's {_sw_id.get('job_parts')} part(s).\n"
                          f"                {_why}\n"
                          f"                extract codes: "
                          f"{', '.join(_sw_id.get('extract_codes') or []) or '(none)'}\n"
                          f"                job codes:     "
                          f"{', '.join(_sw_id.get('job_codes') or []) or '(none)'}\n"
                          f"                extract: {_sw_job.meta.get('extract_path')}\n"
                          f"                Nothing from it has been applied — this job is "
                          f"costed from drawings alone.", flush=True)
                    summary["solidworks_native"] = {
                        "source": "solidworks_api",
                        "found": False,
                        "refused_wrong_job": True,
                        "refused_own_job": bool(_ours),
                        "extract_path": _sw_job.meta.get("extract_path"),
                        "extract_top_assembly": _sw_id.get("top_assembly"),
                        "extract_part_count": _sw_id.get("candidates"),
                        "job_part_count": _sw_id.get("job_parts"),
                        "extract_codes": _sw_id.get("extract_codes"),
                        "job_codes": _sw_id.get("job_codes"),
                        "reason": _why,
                    }
                    _sw_job = None
                    _sw_why = f"extract refused as belonging to another job: {_why}"
            if _sw_job and _sw_job.found:
                _swc = apply_native_to_pre_estimate(_pre_estimate_parts, _sw_job)
                summary.setdefault("manufacturing_writeup", {})["parts"] = _pre_estimate_parts
                # Keep the normalised extract on the summary so the estimator can audit the
                # modelled source data behind every native-sourced number.
                summary["solidworks_native"] = {
                    "source": "solidworks_api",
                    # SUCCESS SAYS SO IN THE SAME WORD FAILURE USES. Both refusal paths
                    # write "found": False and this one wrote nothing, so a reader asking
                    # the obvious question got None on a perfectly good extract — the tree
                    # was applied, the geometry was applied, and the record said "unknown".
                    "found": True,
                    "reliability": 1.0,
                    "extract_path": _sw_job.meta.get("extract_path"),
                    "top_assembly": _sw_job.meta.get("top_assembly"),
                    "counts": _sw_job.meta.get("counts"),
                    "applied": _swc,
                    # Freshness, carried onto the job so an invariant can act on it.
                    "extract_stale": bool(_sw_job.meta.get("extract_stale")),
                    "extract_incomplete": bool(_sw_job.meta.get("extract_incomplete")),
                    "manifest_absent": bool(_sw_job.meta.get("manifest_absent")),
                    "freshness_unverifiable": bool(_sw_job.meta.get("freshness_unverifiable")),
                    "fingerprint_folder": _sw_job.meta.get("fingerprint_folder"),
                    "source_unreachable": bool(_sw_job.meta.get("source_unreachable")),
                    "changed_during_extraction": bool(_sw_job.meta.get("changed_during_extraction")),
                    "fingerprint_before": _sw_job.meta.get("fingerprint_before"),
                    "extract_errors": _sw_job.meta.get("extract_errors"),
                    "freshness_check": _sw_job.meta.get("freshness_check"),
                    "files_read": _sw_job.meta.get("files_read"),
                    "files_failed": _sw_job.meta.get("files_failed"),
                    "native_files_present": _sw_job.meta.get("native_files_present"),
                    "native_files_fingerprint": _sw_job.meta.get("native_files_fingerprint"),
                    "analyser_error": _sw_job.meta.get("analyser_error"),
                    "bom": [vars(r) for r in _sw_job.bom],
                }
                if _sw_job.meta.get("extract_stale"):
                    print("   [solidworks] EXTRACT IS STALE — the native models have changed "
                          "since it was taken. The estimate is built on older geometry and "
                          "is PROVISIONAL until the extract is regenerated.", flush=True)
                print(f"   [solidworks] native extract applied — flat+{_swc['flat']} "
                      f"thickness+{_swc['thickness']} material+{_swc['material']} "
                      f"bends+{_swc['bends']} qty+{_swc['qty']} "
                      f"assembly-parent+{_swc['assembly_parent']} bought-in+{_swc['bought_in']}",
                      flush=True)
                if _swc["material_conflict"] or _swc["geometry_conflict"]:
                    print(f"   [solidworks] {_swc['material_conflict']} material and "
                          f"{_swc['geometry_conflict']} blank disagreement(s) with the drawing "
                          f"— flagged on the part, drawing value kept", flush=True)
                if _swc["no_geometry_flagged"]:
                    print(f"   [solidworks] {_swc['no_geometry_flagged']} part(s) have a "
                          f"material but NO usable geometry — flagged as unpriced, NOT £0",
                          flush=True)
                if _swc["rejected_values"] or _swc["geometry_unchecked"]:
                    print(f"   [solidworks] {_swc['rejected_values']} modelled value(s) READ "
                          f"BUT REJECTED by the geometry gates, {_swc['geometry_unchecked']} "
                          f"blank(s) left unreconciled against the DXF — both flagged on the "
                          f"part, neither silently dropped", flush=True)
                if _swc["not_in_bom"]:
                    print(f"   [solidworks] {_swc['not_in_bom']} modelled part(s) appear in "
                          f"NO assembly BOM (fixture/jig/setup) — flagged, confirm before "
                          f"costing", flush=True)
            elif _sw_flag in {"1", "true", "yes", "on"}:
                print("   [solidworks] NOT APPLIED — no _sw_native_extract.json for this job "
                      "(run tools/solidworks/sw_native_analyse.py on the model folder)", flush=True)
        except Exception as _e_sw:
            print(f"   [solidworks] skipped ({_e_sw})", flush=True)
            _sw_why = f"the connector raised {type(_e_sw).__name__}: {_e_sw}"

    # ── Whole-document LLM extract — DRIVE the estimate from a chat-session-style read ──
    # Gated (SDI_LLM_FULL_EXTRACT). Reasons over the ENTIRE pack in one call (hierarchy + tube
    # cut lengths + materials + weights) and folds it into the pre-estimate parts BEFORE costing,
    # so the engine's own tube/weight paths fire with the real data instead of garbled per-page
    # vision geometry. Every value is flagged LLM-sourced (estimator to verify) and is
    # transcribed from the drawing, cross-checked against the deterministic reads. Failure-isolated.
    import os as _os_llm
    # Default ON for PDF jobs when an XAI_API_KEY is present — the DXF waterfall keeps measured
    # parts safe (LLM only fills gaps there), so the extract is safe on every job and this removes
    # the silent no-op where the flag was simply never set and the good data never reached costing.
    # Explicit SDI_LLM_FULL_EXTRACT=0/false/no/off disables it; =1/true/yes/on forces it on.
    _llm_flag = _os_llm.getenv("SDI_LLM_FULL_EXTRACT", "").strip().lower()
    _llm_off = _llm_flag in {"0", "false", "no", "off"}
    _llm_on = (_llm_flag in {"1", "true", "yes", "on"}
               or (_llm_flag == "" and bool(_os_llm.getenv("XAI_API_KEY"))))
    if pdf_path and _llm_on and not _llm_off:
        try:
            from llm_full_extract import extract_full_job
            from source_connectors.llm_full_job import apply_full_job_to_pre_estimate, overlay_drawing_facts
            _job = extract_full_job(str(pdf_path))
            if _job.get("found"):
                # Overlay the DETERMINISTIC drawing_facts onto the LLM job: printed title-block
                # values (per-part finish/thickness) fill the LLM's nulls, and the weld spec is
                # combined (LLM 'set-down 20%' + deterministic 'ALL WELDS TO BE TIG'). Best of both.
                try:
                    from drawing_facts import extract_drawing_facts
                    overlay_drawing_facts(_job, extract_drawing_facts(str(pdf_path)))
                except Exception as _e_ov:
                    print(f"   [llm-full-extract] overlay skipped ({_e_ov})", flush=True)
                # SECOND PASS — what the drawing IMPLIES but does not print. The pass above
                # is forbidden from inventing, and rightly so; on a GA-only pack that leaves
                # parts with no material and no size, which nothing downstream can price or
                # route. M&S 2085 booked GBP 2.00 of labour on a welded three-part bracket
                # because neither tube carried a single operation.
                #
                # Asked only about parts the first pass left empty, and everything it returns
                # is stamped `inference` — the lowest rank in the waterfall — so it can never
                # overwrite a printed or measured value. Failure-isolated: no model, no key,
                # or a refusal all leave the job exactly as it is today.
                try:
                    from llm_full_extract import (build_document_context,
                                                  infer_missing_details, merge_inference,
                                                  parts_missing_detail)
                    _missing = parts_missing_detail(_job.get("parts") or [])
                    if _missing:
                        _inf = infer_missing_details(
                            build_document_context(str(pdf_path)),
                            _job.get("bom") or [], _missing)
                        if _inf.get("found"):
                            _job["inferred_parts"] = _inf.get("parts")
                            _job["inferred_routes"] = _inf.get("routes")
                            # THE WELD LIVES HERE, NOT IN THE TRANSCRIPTION.
                            # Keeping the raw response was for answering "did the model say
                            # welding?" — and welding is a CONCLUSION, so it comes from the
                            # inference pass. Surfacing only the transcription raw answered
                            # a question nobody was asking and left the one that cost a
                            # commit-diff argument still unanswerable from the deliverable.
                            _job["_inferred_raw_response"] = _inf.get("_raw_response")
                            _job["_inference_from_cache"] = bool(_inf.get("_from_cache"))
                            # MERGE, not stash. Stashing it on the job was the whole of the
                            # last attempt: apply_full_job_to_pre_estimate reads job["parts"]
                            # and job["routes"] and nothing else, so the inference sat beside
                            # the job it was meant to complete and never reached a price.
                            _mc = merge_inference(_job, _inf)
                            print(f"   [llm-inference] {len(_inf.get('parts') or [])} part(s) had "
                                  f"no material or size printed — filled {_mc['fields']} field(s), "
                                  f"added {_mc['parts_added']} part(s) and {_mc['routes']} route(s), "
                                  f"all stamped 'inference' (lowest rank, never overwrites a "
                                  f"measurement)", flush=True)
                        else:
                            print(f"   [llm-inference] {len(_missing)} part(s) have nothing "
                                  f"printed to cost from and inference returned nothing — "
                                  f"they stay empty rather than guessed", flush=True)
                except Exception as _e_inf:
                    print(f"   [llm-inference] skipped ({_e_inf}) — run continues", flush=True)

                _c = apply_full_job_to_pre_estimate(_pre_estimate_parts, _job)
                summary.setdefault("manufacturing_writeup", {})["parts"] = _pre_estimate_parts
                # Keep the WHOLE extract on the summary so it can be dumped to a retrievable
                # sidecar next to the deliverables — this is the transcribed source data the
                # estimator can audit against (BOM hierarchy, tube cut lengths, weights, spec).
                summary["llm_full_extract"] = {
                    "source": _job.get("source"),
                    "top_assembly": _job.get("top_assembly"),
                    "bom": _job.get("bom"),
                    "routes": _job.get("routes"),
                    "assemblies": _job.get("assemblies"),
                    "parts": _job.get("parts"),
                    "spec": _job.get("spec"),
                    "inferred_parts": _job.get("inferred_parts"),
                    "inferred_routes": _job.get("inferred_routes"),
                    # What the model literally returned, so a route that appears on one run
                    # and not the next can be settled by comparing responses rather than by
                    # inferring from which files a commit happened to touch.
                    "raw_response": _job.get("_raw_response"),
                    "inferred_raw_response": _job.get("_inferred_raw_response"),
                    "prompt_fingerprint": _job.get("_prompt_fingerprint"),
                    "from_cache": bool(_job.get("_from_cache")),
                    "inference_from_cache": bool(_job.get("_inference_from_cache")),
                    "counts": _c,
                }
                print(f"   [llm-full-extract] drove tube+{_c['tube']} qty+{_c.get('qty', 0)} "
                      f"material+{_c['material']} weight+{_c['weight']} thickness+{_c['thickness']} "
                      f"assembly-flagged+{_c['assembly_flagged']} into the estimate", flush=True)
            else:
                print(f"   [llm-full-extract] no job returned ({_job.get('error', '')})", flush=True)
        except Exception as _e_llm:
            print(f"   [llm-full-extract] skipped ({_e_llm})", flush=True)
    elif pdf_path and not _llm_off:
        # Loud, not silent: the extract would have run but there is no API key. This is the
        # exact footgun that made earlier runs quietly ignore the good LLM data.
        print("   [llm-full-extract] NOT RUN — no XAI_API_KEY set (set it, or "
              "SDI_LLM_FULL_EXTRACT=1, so the PDF extract can drive the estimate)", flush=True)

    # SDI Intelligence — Learning Engine pre-scan
    # Runs AFTER augment_summary_with_dxf + pre-estimate normalisation,
    # BEFORE estimate_document, so knowledge-base / LiveOverrides corrections
    # (PartKnowledge material/thickness) are applied before costing.
    try:
        from learning_engine import get_engine
        summary = get_engine().pre_scan(summary, dxf_paths)
    except Exception:
        pass

    # SDI Intelligence — infer dimensions for BOM parts with no DXF, so they
    # cost provisionally instead of £0. Every value is flagged as inferred.
    try:
        from geometry_inference import infer_missing_geometry
        try:
            import corrections_db as _db
        except Exception:
            _db = None
        _inf = infer_missing_geometry(summary, db=_db)
        summary.setdefault("ai_inference", {})["geometry"] = _inf
        if _inf.get("inferred") or _inf.get("still_missing"):
            print(f"   [inference] {len(_inf.get('inferred', []))} no-DXF part(s) given provisional dimensions; {len(_inf.get('still_missing', []))} still £0")
    except Exception as _e:
        print(f"   [inference] skipped: {_e}", flush=True)

    _debug("start estimate_document")
    # ── THE QUANTITY THE JOB IS COSTED AT, DECIDED ONCE, HERE ────────────────────────
    #
    # estimate_document amortises setup as (rate/60 x setup_mins) / qty and reads that qty
    # from this field. A requested quantity that arrives after this line is a label on a
    # price computed for a different batch: at 10 off against a 180 default, the setup
    # component of every operation comes out 18x light and nothing on the sheet says so.
    #
    # An explicit request beats an inferred quantity as well as the default. It is the one
    # fact about a job the customer states directly, and no reading of the drawings
    # outranks being told. Which of the three supplied it is recorded, because "10" from
    # the enquiry and "10" from a default are the same number and not the same evidence.
    _req_qty_raw = os.getenv("SDI_ORDER_QTY", "").strip()
    _req_qty = None
    if _req_qty_raw:
        try:
            _req_qty = max(1, int(float(_req_qty_raw)))
        except (TypeError, ValueError):
            print(f"   [order-qty] IGNORED — SDI_ORDER_QTY={_req_qty_raw!r} is not a number. "
                  f"Costing at the quantity the drawings imply instead.", flush=True)
    if _req_qty:
        # precedence: direct-write ok — this is the JOB HEADER, not a part record. The
        # arbitrated `quantity` the resolver protects is a per-part figure read off a BOM
        # against competing readings of the same drawing; how many units the customer
        # ordered has no competing sources to rank, and being told outranks any reading.
        summary["quantity"] = _req_qty  # precedence: direct-write ok — job header, see above
        summary["assumed_job_quantity"] = _req_qty
        summary["order_quantity_source"] = "requested"
    elif not summary.get("quantity") and not summary.get("assumed_job_quantity"):
        summary["assumed_job_quantity"] = getattr(config, "DEFAULT_JOB_QUANTITY", 180)
        summary["order_quantity_source"] = "default"
    else:
        summary["order_quantity_source"] = "inferred"
    # A GATE NOBODY ASKS REPORTS NOTHING, and every labour figure below hangs off this
    # number. It is stated on every run, whichever way it was arrived at.
    print(f"   [order-qty] costing this job at "
          f"{summary.get('quantity') or summary.get('assumed_job_quantity')} off "
          f"({summary['order_quantity_source']})", flush=True)

    # FINAL phantom-duplicate sweep — runs AFTER inference and any late description
    # merges, immediately before costing. The earlier pre-estimate passes can miss
    # phantoms because (a) PDF geometry rollups populate during estimate_document
    # (so cut_length was still 0 then), and (b) named-part descriptions may not be
    # final yet. This pass uses raw geometry + final descriptions and is the
    # authoritative drop point for None-PN artefacts like "OUTER TUBE 1".
    try:
        _fp = summary.get("manufacturing_writeup", {}).get("parts") or []

        def _pd_core(d: Any) -> str:
            # Strip a trailing qty suffix: "OUTER TUBE 1" -> "OUTER TUBE"
            return re.sub(r"\s+\d+$", "", str(d or "").strip().upper())

        def _pd_cut(p: Dict[str, Any]) -> int:
            g = p.get("geometry_rollup") or p.get("geometry") or {}
            c = g.get("estimated_cut_length_mm")
            if not c:
                c = (g.get("_raw") or {}).get("estimated_cut_length_mm")
            try:
                return round(float(c or 0))
            except Exception:
                return 0

        _named = [p for p in _fp if p.get("part_number")]
        _named_cores = {_pd_core(p.get("description")) for p in _named if p.get("description")}
        _named_sigs = set()
        for p in _named:
            c = _pd_cut(p)
            if c > 0:
                for pg in (p.get("pages") or []):
                    _named_sigs.add((pg, c))

        _kept = []
        _dropped = []
        for p in _fp:
            if p.get("part_number"):
                _kept.append(p)
                continue
            # Never drop a part that carries its own flat DXF — it is a real part.
            if p.get("dxf_augmented") or str(p.get("geometry_source") or "").lower().startswith("dxf"):
                _kept.append(p)
                continue
            _core = _pd_core(p.get("description"))
            if _core and _core in _named_cores:
                _dropped.append(p.get("description"))
                continue
            _c = _pd_cut(p)
            if _c > 0 and any((pg, _c) in _named_sigs for pg in (p.get("pages") or [])):
                _dropped.append(p.get("description"))
                continue
            _kept.append(p)

        if _dropped:
            summary["manufacturing_writeup"]["parts"] = _kept
            print(f"   [dedup] dropped {len(_dropped)} phantom duplicate part(s): "
                  f"{', '.join(str(d) for d in _dropped)}", flush=True)
    except Exception as _e:
        print(f"   [dedup] final phantom sweep skipped: {_e}", flush=True)

    # -- BOM tree: stamp effective per-bay quantities onto parts --
    # Runs BEFORE estimate_document so quantities feed into costing correctly.
    # Multiplies parent GA qty into children (e.g. 3886-GA x2 -> children x2 per bay).
    try:
        import re as _re_bt
        from bom_tree import resolve_effective_quantities as _resolve_eff_qty
        from bom_tree import merge_table_bom_rows as _merge_bom_rows
        _bt_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
        _bt_rows = _merge_bom_rows(_bt_rows, summary)
        _effmap = (_resolve_eff_qty(_bt_rows) or {}).get("effective") or {}
        if _effmap:
            _parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
            for _p in _parts:
                _code = _re_bt.sub(r"\s+", "", str(_p.get("part_number") or "")).upper()
                _eff = _effmap.get(_code)
                if _eff is not None and _eff != _p.get("quantity"):
                    # PRECEDENCE. This pass reads the PDF's GA table; a quantity already set
                    # from the SolidWorks assembly BOM came from the structure the shop
                    # builds from, and must not be silently replaced by a reading of a
                    # printed table. apply_field keeps the stronger value and records the
                    # disagreement so an estimator sees that two sources differed.
                    from source_precedence import apply_field as _apply_qty
                    _prev = _p.get("quantity")
                    if _apply_qty(_p, "quantity", _eff, "bom_tree"):
                        print(f"   [bom_tree] {_p.get('part_number')} qty {_prev} -> {_eff} (GA tree)", flush=True)
                    else:
                        print(f"   [bom_tree] {_p.get('part_number')} qty {_prev} KEPT "
                              f"(GA tree said {_eff}) — stronger source, disagreement flagged",
                              flush=True)
    except Exception as _bte:
        print(f"   [bom_tree] skipped: {_bte}", flush=True)

    # ── THE CANONICAL GRAPH IS AN AUTHORITY, NOT AN AFTER-THE-FACT REPORT ──────────────
    #
    # The compiler ran only after estimate_part. At that point it could state that
    # 11350-01-101 is an assembly and that a row is bought-in — and the workbook had already
    # charged 101 as a 2.5mm fabricated leaf, with its own laser and fold, on top of the bar
    # it is made from. A graph that describes what pricing already did cannot correct it.
    #
    # Failure-isolated: a compile error leaves the run exactly as it was before this existed.
    # ── THE MIRRORED FLAT, AT THE POINT EVERY PART EXISTS ─────────────────────────────
    #
    # apply_mirror_geometry also runs inside augment_summary_with_dxf, and on 11350 it found
    # nothing to do: "11350-01-02 MIR" is created by the LLM full extract five hundred lines
    # LATER. The rule was right, the fixtures were right, and it ran before the part it was
    # written for existed — so the right arm reached costing with no blank, no material and
    # no measured throughput, and the sheet under-read.
    #
    # Running it here as well is safe by construction, not by luck: it gap-fills only, skips
    # any part that already has a blank, and refuses a base whose own flat was inherited. A
    # second pass over parts it has already filled changes nothing. The earlier call stays
    # because augment_summary_with_dxf is also the standalone DXF-merge entry point.
    # ── THE SAME SEAM, FOR THE MODELS ─────────────────────────────────────────────────
    #
    # apply_native_to_pre_estimate runs at line ~1979. The LLM full extract creates parts at
    # ~2116. On 11350 that is 137 lines between the models being applied and
    # "11350-01-02 MIR" existing — and the pack contains Mirror11350-01-02M.SLDPRT, so the
    # right arm has its OWN model, at rank 90, better evidence than the inherited flat. It
    # reached costing with thickness 0 and fallback throughput because the connector had
    # already run before the part was born.
    #
    # ONLY THE PARTS THAT MISSED IT. 27 of the connector's 28 review-flag appends are
    # unguarded, so re-running it over parts it has already enriched would duplicate every
    # QA message on the job. Restricted to records with no solidworks_native marker, this
    # adds evidence and repeats nothing.
    try:
        from source_connectors.solidworks import apply_native_to_pre_estimate as _apply_native
        # The accepted extract is still bound in this function — _sw_job is initialised
        # before the branch above and only cleared when the extract was refused. Read it
        # directly rather than through locals(), which cannot tell an unbound name from a
        # refused extract and so turned every failure mode into the same silent None.
        _sw_job_late = _sw_job
        _missed = [p for p in summary["manufacturing_writeup"]["parts"]
                   if isinstance(p, dict) and not p.get("solidworks_native")]
        if _sw_job_late is not None and getattr(_sw_job_late, "found", False) and _missed:
            _lc = _apply_native(_missed, _sw_job_late)
            _got = [p.get("part_number") for p in _missed if p.get("solidworks_native")]
            if _got:
                print(f"   [solidworks] applied to {len(_got)} part(s) that did not exist "
                      f"when the models were first read: {', '.join(str(g) for g in _got)}",
                      flush=True)
        # THE MODEL'S OWN TREE, ONTO THE WHOLE POPULATION. Stamped separately from the
        # geometry apply above because that one deliberately skips parts already carrying
        # native evidence — and an assembly's CHILDREN are exactly the fact a part can be
        # missing while every other native datum on it is present. Runs before the canonical
        # graph is compiled, so a node arrives with its parent rather than being repaired
        # after it is already flagged disconnected.
        #
        # A GATE NOBODY ASKS REPORTS NOTHING — and the last version of this reported nothing
        # for the one state it was written to explain. The three-state message below sat
        # INSIDE `if the extract was accepted`, so an absent, refused or unread extract
        # produced no [hierarchy] line at all, which is indistinguishable from the pass not
        # existing. Every path now prints exactly one line, and the reason travels onto the
        # summary as well as the console, because an estimator running this unattended from
        # the intranet never sees a console at all.
        _hier: List[Dict[str, Any]] = []
        _msg = ""
        if _sw_job_late is None or not getattr(_sw_job_late, "found", False):
            _msg = f"no SolidWorks extract was applied to this job — {_sw_why or 'reason not recorded'}"
        else:
            from source_connectors.solidworks import apply_native_hierarchy_to_parts
            _hier = apply_native_hierarchy_to_parts(
                summary["manufacturing_writeup"]["parts"], _sw_job_late)
            for _h in _hier:
                print(f"   [hierarchy] {_h['part_number']} holds "
                      f"{', '.join(_h['children'])} (from the SolidWorks model)", flush=True)
            _sw_meta = getattr(_sw_job_late, "meta", {}) or {}
            _edges = sum(len(v) for v in (getattr(_sw_job_late, "hierarchy", {}) or {}).values())
            _asms = len(getattr(_sw_job_late, "assembly_pns", []) or [])
            _asm_recs = int(_sw_meta.get("hierarchy_assembly_records") or 0)
            if not _hier:
                if _edges:
                    _msg = (f"the extract carries {_edges} parent/child edge(s) but none named "
                            f"a part in this job — the codes in the models and the codes on "
                            f"the drawing may not match. Model parents: "
                            f"{', '.join(_sw_meta.get('hierarchy_parents') or []) or '(none)'}")
                elif _asms or _asm_recs:
                    _msg = (f"{_asms or _asm_recs} assembly document(s) were read and NONE "
                            f"reported parent/child edges or BOM-line parents. The extract "
                            f"predates the analyser change, or this SolidWorks build returns "
                            f"no component parents. "
                            f"Re-run tools/solidworks/sw_native_analyse.py, then this job")
                else:
                    _msg = ("the extract contains no assembly documents, so the models "
                            "describe no hierarchy to apply")
            # THE TREE ITSELF, ON THE SUMMARY. The console line answers "did it fire"; this
            # answers "what did it say" from the saved job JSON alone, which is the only
            # record an unattended run leaves behind.
            _sw_block = summary.get("solidworks_native")
            if isinstance(_sw_block, dict):
                _sw_block["hierarchy"] = {
                    str(_p): [[str(_c), float(_q)] for _c, _q in _kids]
                    for _p, _kids in (getattr(_sw_job_late, "hierarchy", {}) or {}).items()}
                _sw_block["hierarchy_edges"] = _edges
                _sw_block["hierarchy_sources"] = _sw_meta.get("hierarchy_sources") or {}
                _sw_block["hierarchy_applied"] = [
                    {"part_number": _h["part_number"], "children": list(_h["children"])}
                    for _h in _hier]
        if _msg:
            print(f"   [hierarchy] NOT APPLIED — {_msg}", flush=True)
            summary.setdefault("review_flags", []).append(
                f"SolidWorks hierarchy not applied: {_msg}. Any part left without a "
                f"parent is reported separately as a disconnected BOM node.")
        else:
            print(f"   [hierarchy] applied to {len(_hier)} assembly node(s) from the "
                  f"SolidWorks models", flush=True)
    except Exception as _sw_late_err:
        print(f"   [solidworks] late application skipped: "
              f"{type(_sw_late_err).__name__}: {_sw_late_err}", flush=True)

    # ── THE SAME SEAM, FOR THE HIERARCHY THE DESCRIPTION STATES ───────────────────────
    #
    # "<A> WITH <B>" needs BOTH halves to be lines on this BOM, and on 11350 the PEM stud is
    # created by the LLM extract and the dual-path reader — after the DXF pass where the rule
    # ran. So 11350-01-101's children were never recorded, and 11350-01-01, BI-NUT and
    # BI-PEMSTUD arrived at the compiler with no parent: two bom_node_disconnected blockers
    # on a job whose hierarchy we can read perfectly well.
    #
    # Same idempotency as the mirror pass: a part already marked an assembly parent is
    # skipped, and the flag is appended once.
    try:
        from drawing_job_merge import _stamp_assembly_parents
        _stamp_assembly_parents(summary["manufacturing_writeup"]["parts"])
    except Exception as _asm_err:
        print(f"   [hierarchy] description pass skipped: "
              f"{type(_asm_err).__name__}: {_asm_err}", flush=True)

    # ONE ITEM READ TWICE IS ONE PART, and it must stop being two BEFORE the canonical
    # graph is compiled — a phantom that becomes a node has to be repaired afterwards,
    # which is how a truncated stem reached the sheet as its own unpriceable line.
    try:
        from drawing_job_merge import merge_truncated_part_codes
        _bom_merged = merge_truncated_part_codes(
            summary["manufacturing_writeup"]["parts"],
            claimed_codes=_codes_claimed_by_the_hierarchy(summary))
        for _m in _bom_merged:
            print(f"   [bom] '{_m['part_number']}' merged into '{_m['merged_into']}' "
                  f"({_m.get('reason') or 'truncated code'}; qty {_m['quantity']:g})",
                  flush=True)
    except Exception as _bm_err:
        print(f"   [bom] truncated-code merge skipped: "
              f"{type(_bm_err).__name__}: {_bm_err}", flush=True)

    try:
        from drawing_job_merge import apply_mirror_geometry
        _mirrored = apply_mirror_geometry(summary["manufacturing_writeup"]["parts"])
        if _mirrored:
            print("   [mirror] " + "; ".join(
                f"{m.get('part_number')} inherits the measured flat of {m.get('mirrored_from')}"
                for m in _mirrored), flush=True)
    except Exception as _mirror_err:
        print(f"   [mirror] skipped: {type(_mirror_err).__name__}: {_mirror_err}", flush=True)

    try:
        from route_compiler import apply_canonical_evidence_to_parts, job_drawing_numbers
        # THE BOM'S OWN PARENT EDGES, at the point the classification still changes the
        # answer. This runs before costing, so a part the BOM parents is an assembly's child
        # here rather than a disconnected leaf that has already been priced as one.
        _canon_pre = apply_canonical_evidence_to_parts(
            summary["manufacturing_writeup"]["parts"],
            summary.get("llm_full_extract") or {},
            (summary.get("document_analysis") or {}).get("bom_rows") or [],
            job_drawing_numbers(summary),
            assembly_page_owners(summary))
        summary["canonical_part_graph_pre_cost"] = {
            "nodes": len(_canon_pre.get("nodes") or []),
            "issues": list(_canon_pre.get("issues") or []),
            "roots": list(_canon_pre.get("top_assemblies") or []),
        }
        _roots = [r for r in (_canon_pre.get("top_assemblies") or []) if r]
        print(f"   [canonical-part-graph] applied before costing: "
              f"{len(_canon_pre.get('nodes') or [])} node(s)"
              + (f"; {len(_roots)} assemblies ship on this enquiry ({', '.join(_roots)})"
                 if len(_roots) > 1 else ""), flush=True)
    except Exception as _canon_pre_err:
        print(f"   [canonical-part-graph] pre-cost application skipped: "
              f"{type(_canon_pre_err).__name__}: {_canon_pre_err}", flush=True)

    # AND AGAIN, AT THE LAST BOUNDARY BEFORE COSTING.
    #
    # The merge above protects the canonical graph, and something between there and here
    # re-creates the phantoms: the renderer's own [bom-rows] line showed SCREW, STD PART,
    # 79814P and FIXING back in the costed population after they had been removed from the
    # parts. A pass materialises the drawing's raw BOM lines as parts, and it runs later.
    #
    # Rather than a third guess at which pass, the same rule runs once more at the point
    # nothing can add a part after it. It is idempotent — a stem with no fuller code beside
    # it is left alone — so the second call is free on a job the first one already settled,
    # and part_identity remains the single authority both calls ask.
    try:
        from drawing_job_merge import merge_truncated_part_codes as _merge_late
        _late = _merge_late(summary["manufacturing_writeup"]["parts"],
                            claimed_codes=_codes_claimed_by_the_hierarchy(summary))
        for _m in _late:
            print(f"   [bom] '{_m['part_number']}' merged into '{_m['merged_into']}' "
                  f"(re-created after the first pass; qty {_m['quantity']:g})", flush=True)
    except Exception as _lm_err:
        print(f"   [bom] late truncated-code merge skipped: "
              f"{type(_lm_err).__name__}: {_lm_err}", flush=True)

    # AND THE LEAF-OPERATION STRIP AGAIN, AT THE LAST BOUNDARY BEFORE COSTING.
    #
    # apply_canonical_evidence_to_parts removes them where it classifies a record as an
    # assembly, and on 12392 they were back by the time the invariants ran: 12392-02-201 was
    # reported carrying folding and laser_cutting on a workbook whose own log says the
    # assembly was excluded from material. Something between the two re-derives operations
    # from the drawing text.
    #
    # This is the same answer the truncated-code merge above reaches for the same reason:
    # rather than a third guess at which pass, the rule runs once more at the point nothing
    # can add an operation after it. strip_leaf_operations is idempotent and does nothing at
    # all to a record the graph has not called an assembly, so the second call is free on a
    # job the first one settled.
    try:
        import bought_in_policy as _bip
        for _p in summary["manufacturing_writeup"]["parts"]:
            _late_dropped = _bip.strip_leaf_operations(_p)
            if _late_dropped:
                _p.setdefault("removed_operations", []).extend(_late_dropped)
                print(f"   [route] '{_p.get('part_number')}' is an assembly and had "
                      f"{', '.join(_late_dropped)} put back on it after the first strip; "
                      f"removed again — that work belongs to its children", flush=True)
    except Exception as _strip_err:
        print(f"   [route] late leaf-operation strip skipped: "
              f"{type(_strip_err).__name__}: {_strip_err}", flush=True)

    summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"], summary=summary)
    _debug("done estimate_document")

    # UNCONDITIONAL recon probe (temporary): proves this branch is reached and shows the env +
    # _dp state here, independent of the dual-path gate below. Remove once diagnosed.
    try:
        _dp_probe_state = f"defined rows={len((_dp or {}).get('rows') or [])}" if isinstance(_dp, dict) else f"defined non-dict:{type(_dp).__name__}"
    except NameError:
        _dp_probe_state = "NOT-DEFINED"
    print(f"   [recon-probe] post-estimate_document reached | scan_mode={summary.get('scan_mode')!r} | "
          f"dual_path={_dual_path_enabled()} | _dp={_dp_probe_state}", flush=True)

    # Dual-path -> part_estimates reconcile: runs HERE, AFTER estimate_document has built
    # part_estimates, so the fastener corrections (self-clinch 1->4, knob 1->2, add
    # BI-PEMSTUD) land on the FINAL list the sheet reads. The earlier inline copy ran
    # before part_estimates existed and silently no-op'd (STATUS doc S3.3).
    if _dual_path_enabled():
        try:
            _dp_after = _dp  # defined above when the dual path ran; NameError-guarded
            # DIAGNOSTIC (temporary): show the runtime inputs so a silent no-op is explainable.
            _dp_rows_diag = (_dp_after.get("rows") or []) if isinstance(_dp_after, dict) else None
            _pe_diag = (summary.get("estimate_summary") or {}).get("part_estimates")
            _fast_diag = [str(r.get("description") or r.get("part_number") or "?")
                          for r in (_dp_rows_diag or [])][:14]
            _a_cnt = _dp_after.get("a_count") if isinstance(_dp_after, dict) else "?"
            _b_cnt = _dp_after.get("b_count") if isinstance(_dp_after, dict) else "?"
            _pdf_cnt = len(_dp_after.get("pdf_paths") or []) if isinstance(_dp_after, dict) else "?"
            print(f"   [dual-path recon:diag] _dp rows={len(_dp_rows_diag) if _dp_rows_diag is not None else 'NOT-A-DICT'} "
                  f"pathA_tables={_a_cnt} pathB_tables={_b_cnt} pdfs_found={_pdf_cnt} "
                  f"part_estimates={len(_pe_diag) if isinstance(_pe_diag, list) else 'NONE'} "
                  f"dp_row_descs={_fast_diag}", flush=True)
            _u, _a = _reconcile_dualpath_into_part_estimates(summary, _dp_after)
            print(f"   [dual-path recon] part_estimates: {_u} qty-corrected, {_a} added from BOM table read", flush=True)
        except NameError:
            print("   [dual-path recon:diag] _dp is NOT DEFINED at reconcile point (dual-path reader did not run this path)", flush=True)
        except Exception as _dpr2_err:
            print(f"   [dual-path recon:diag] reconcile errored: {type(_dpr2_err).__name__}: {_dpr2_err}", flush=True)

    # ── THE OTHER TIMING BOUNDARY ─────────────────────────────────────────────────────
    # The dual-path table reader adds bought-ins AFTER the route was compiled, which is how
    # 11350's wing nuts and PEM studs reached the Estimate tab and the reports while the
    # canonical BOM had never heard of them. Two BOM authorities, and the one an estimator
    # reads was the one outside the graph. Recompile from the final population.
    try:
        from route_compiler import refresh_canonical_route_after_reconciliation
        _canon_final = refresh_canonical_route_after_reconciliation(summary)
        print(f"   [canonical-part-graph] refreshed after BOM reconciliation: "
              f"{len(_canon_final.get('nodes') or [])} node(s)", flush=True)
    except Exception as _canon_refresh_err:
        print(f"   [canonical-part-graph] post-reconcile refresh failed: "
              f"{type(_canon_refresh_err).__name__}: {_canon_refresh_err}", flush=True)

    try:
        import bay_rollup
        import estimator as _estimator_mod

        bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
        part_estimates = (summary.get("estimate_summary") or {}).get("part_estimates") or []
        if summary.get("scan_mode") == "folder_as_job" and part_estimates:
            bom_rows = bay_rollup.synthesize_folder_job_bom_rows(summary, part_estimates)
            summary.setdefault("document_analysis", {})["bay_bom_rows"] = bom_rows
        try:
            from part_identity import inject_missing_bay_rows

            bom_rows = inject_missing_bay_rows(bom_rows, summary)
        except Exception:
            pass
        if bom_rows and part_estimates:
            order_qty = (
                summary.get("quantity")
                or summary.get("assumed_job_quantity")
                or getattr(config, "DEFAULT_JOB_QUANTITY", 180)
            )
            pricer = bay_rollup.make_system_cost_pricer(_estimator_mod._resolve_part_system_cost)
            try:
                import bought_in_pricing as _bip

                _pb_cache = getattr(config, "PRICE_BOOK_CACHE", config.OUTPUT_DIR / "price_book.json")
                _book = _bip.load_cached_price_book(_pb_cache)
                if _book:
                    pricer = _bip.combine_pricers(
                        _bip.make_price_book_pricer(_book, int(order_qty)), pricer
                    )
                    print(f"   [bay] price book applied: {len(_book)} bought-in item(s)")
            except Exception as _pb_err:
                _debug(f"[bay] price book not applied: {_pb_err}")
            bay_out = bay_rollup.build_bay_estimate(
                bom_rows,
                part_estimates,
                order_quantity=int(order_qty),
                catalogue_pricer=pricer,
            )
            if summary.get("scan_mode") == "folder_as_job" and not bay_rollup.job_has_costing_root(bom_rows, summary):
                bay_out["headline_suppressed"] = True
                bay_out["bay_unit_total_gbp"] = None
                bay_out.setdefault("flags", []).append(
                    {
                        "severity": "warning",
                        "line": "costing_root",
                        "detail": "No top-level bay GA PDF in folder — BOM synthesized from sub-drawings; verify lines",
                    }
                )
            summary["bay_estimate"] = bay_out
            _be = summary["bay_estimate"]
            print(
                f"   [bay] provisional £{_be.get('bay_unit_total_provisional_gbp')} "
                f"confident £{_be.get('bay_unit_total_confident_gbp')} "
                f"coverage {_be.get('line_coverage')} "
                f"({_be.get('provisional_lines', 0)} provisional, "
                f"{_be.get('uncosted_lines', 0)} uncosted)",
                flush=True,
            )
    except Exception as _be_err:
        print(f"   [bay] rollup skipped: {_be_err}", flush=True)

    _debug("start _build_additive_summary_sections")
    _build_additive_summary_sections(summary)
    _debug("done _build_additive_summary_sections")
    _debug("start normalise_json")
    summary = normalise_json(summary)
    _debug("done normalise_json")

    _debug("start write_outputs")
    output_paths = write_outputs(summary)
    _debug("done write_outputs")
    return summary, output_paths
