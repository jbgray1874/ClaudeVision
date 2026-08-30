import json
import os
import re
import shutil
import time
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def list_input_files(search_root: Path = config.DRAWINGS_DIR, drawing_pattern: str = "*") -> List[Path]:
    if not search_root.exists():
        return []
    paths = sorted(
        [
            path
            for path in search_root.glob(drawing_pattern)
            if path.is_file() and path.suffix.lower() in config.SUPPORTED_EXTENSIONS
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
        key = path.parent.resolve()
        groups.setdefault(key, []).append(path)
    for folder in groups:
        groups[folder] = sorted(groups[folder], key=lambda p: p.name.lower())
    return groups


def _normalize_bom_part_key(part_number: Any) -> str:
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

    bom_by_key: Dict[str, Dict[str, Any]] = {}
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
            key = _normalize_bom_part_key(row.get("part_number"))
            if not key:
                continue
            row_copy = dict(row)
            row_copy["source_pdf"] = pdf_path.name
            existing = bom_by_key.get(key)
            if existing is None or _bom_row_merge_preferred(row_copy, existing, pdf_path, primary_pdf):
                bom_by_key[key] = row_copy

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
    merged_doc["bom_rows"] = list(bom_by_key.values())
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
    part_numbers = [
        p for p in part_numbers
        if not any(p.upper().endswith(s.upper()) for s in _junk_sfx)
        and not re.match(r"^\d{4}\s*-\s*[A-Z]{2,}$", p.upper())
        and not p.upper().startswith(("C-C", "MMM", "UPC-", "RAL"))
    ]
    bom_row_count = len(re.findall(config.QTY_TABLE_ROW_PATTERN, full_text, flags=re.IGNORECASE))
    unique_part_numbers = sorted(set(part_numbers))
    detail_cues = any(token in full_text.upper() for token in ["FLAT PATTERN", "DETAIL "])
    drawing_assembly_hint = "ASSEMBLY" in normalize_text(title_block_text).upper()
    title_block_drawing_numbers = re.findall(config.DRAWING_NUMBER_PATTERN, normalize_text(title_block_text), flags=re.IGNORECASE)
    title_block_drawing_number_count = len(title_block_drawing_numbers)
    page_text_upper = normalize_text(page_text).upper()
    bom_header_detected = (
        "ITEM" in page_text_upper
        and "QTY" in page_text_upper
        and any(t in page_text_upper for t in ("DWG NO", "PARTNO", "PART NO", "PART NUMBER"))
    )

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
        existing = str(part.get("normalized_material") or "").strip()
        if existing and existing not in ("?", "", "None", "UNKNOWN"):
            continue
        if part.get("materials"):
            continue
        if doc_mat_norm:
            part["normalized_material"] = doc_mat_norm
            part.setdefault("material_inherited_from", "document_level")
        if doc_mat_raw and not part.get("materials"):
            part["materials"] = [doc_mat_raw]
            part.setdefault("material_inherited_from", "document_level")


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
    _debug("start build_document_writeup")
    summary["manufacturing_writeup"] = build_document_writeup(summary)
    _debug("done build_document_writeup")

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
                    _part[_dim_field] = None
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
        for _di, _dp in enumerate(_pre_estimate_parts):
            _gr = _dp.get("geometry_rollup") or _dp.get("geometry") or {}
            _cut = round(float(_gr.get("estimated_cut_length_mm") or 0))
            if _cut <= 0:
                continue
            _dk = (tuple(sorted(_dp.get("pages") or [])), _cut)
            if _dk not in _by_geom:
                _by_geom[_dk] = _di
                continue
            _prev_i = _by_geom[_dk]
            _prev_p = _pre_estimate_parts[_prev_i]
            if _dp.get("part_number") and not _prev_p.get("part_number"):
                _drop_idx.add(_prev_i)
                _by_geom[_dk] = _di
            elif not _dp.get("part_number") and _prev_p.get("part_number"):
                _drop_idx.add(_di)
            elif not _dp.get("part_number") and not _prev_p.get("part_number"):
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
                        _part["normalized_thickness_mm"] = _tv_thk
            # 1. Set correct normalized_material (BOUGHT_IN, VENEERED_MDF etc.)
            _mat = normalise_material_for_part(_part)
            if _mat:
                _part["normalized_material"] = _mat
            # Fabricated MS flat patterns must not stay BOUGHT_IN (e.g. GRAPHIC CHANNEL).
            if (_part.get("normalized_material") or "").upper() == "BOUGHT_IN":
                _dfn_chk = str(_part.get("dxf_source_file") or _part.get("geometry_source_path") or "").upper()
                if _part.get("flat_pattern_detected") and ("_MS_" in _dfn_chk or " MS_" in _dfn_chk
                        or re.search(r"\d+\.?\d*\s*MM\s*MS", _dfn_chk)):
                    _part["normalized_material"] = "MILD_STEEL"
            # DXF filename material fallback
            if not _part.get("normalized_material"):
                _dfn = str(_part.get("dxf_source_file") or _part.get("geometry_source_path") or "").upper()
                _dgs = str(_part.get("geometry_source") or "")
                if "dxf" in _dgs.lower() and _dfn:
                    if "_MS_" in _dfn or "MS_" in _dfn or "_MS." in _dfn:
                        _part["normalized_material"] = "MILD_STEEL"
                    elif "PETG" in _dfn:
                        _part["normalized_material"] = "ACRYLIC"
                    elif "_ACR_" in _dfn or "ACRYLIC" in _dfn:
                        _part["normalized_material"] = "ACRYLIC"
                    elif "JOINERY" in _dfn or "_MDF_" in _dfn:
                        _part["normalized_material"] = "MDF"
                    elif "DISPA" in _dfn or "PAPER" in _dfn:
                        _part["normalized_material"] = "BOUGHT_IN"
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
    if not summary.get("quantity") and not summary.get("assumed_job_quantity"):
        summary["assumed_job_quantity"] = getattr(config, "DEFAULT_JOB_QUANTITY", 180)

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

    summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"], summary=summary)
    _debug("done estimate_document")

    try:
        import bay_rollup
        import estimator as _estimator_mod

        bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
        part_estimates = (summary.get("estimate_summary") or {}).get("part_estimates") or []
        if summary.get("scan_mode") == "folder_as_job" and part_estimates:
            bom_rows = bay_rollup.synthesize_folder_job_bom_rows(summary, part_estimates)
            summary.setdefault("document_analysis", {})["bay_bom_rows"] = bom_rows
        if bom_rows and part_estimates:
            order_qty = (
                summary.get("quantity")
                or summary.get("assumed_job_quantity")
                or getattr(config, "DEFAULT_JOB_QUANTITY", 180)
            )
            pricer = bay_rollup.make_system_cost_pricer(_estimator_mod._resolve_part_system_cost)
            # Prefer Tim's price-book figures for bought-in / catalogue tokens
            # (ELECTRICS, FIXING*, SUBPLAS*, VINYL*, SLOTTEDTUBE*, ...), falling
            # back to system cost. The master book is built periodically from the
            # historical archive (bought_in_pricing.build_and_cache_master_book);
            # if the cache is absent this is a no-op and we use system cost only.
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
