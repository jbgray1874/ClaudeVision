import json
import os
import re
import shutil
import time
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

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
from geometry_analysis import analyse_document_geometry, calibrate_document_geometry
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


def list_input_files(search_root: Path = config.DRAWINGS_DIR, drawing_pattern: str = "*.pdf") -> List[Path]:
    if not search_root.exists():
        return []
    return sorted([path for path in search_root.glob(drawing_pattern) if path.suffix.lower() in config.SUPPORTED_EXTENSIONS])


def _infer_page_role(page_text: str, bom_text: str, title_block_text: str) -> Dict[str, Any]:
    full_text = normalize_text(f"{page_text} {bom_text} {title_block_text}")
    part_numbers = re.findall(config.PART_NUMBER_PATTERN, full_text, flags=re.IGNORECASE)
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
    return {
        "part_numbers": sorted(set(re.findall(config.PART_NUMBER_PATTERN, normalized, flags=re.IGNORECASE))),
        "dates": sorted(set(re.findall(config.DATE_PATTERN, normalized, flags=re.IGNORECASE))),
        "revision_matches": sorted(set(re.findall(config.REVISION_PATTERN, normalized, flags=re.IGNORECASE))),
        "dimensions_mm": sorted(set(re.findall(config.DIMENSION_PATTERN, normalized, flags=re.IGNORECASE)))[:500],
    }


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
    stem = Path(summary["source_file"]).stem
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


def _build_additive_summary_sections(summary: Dict[str, Any]) -> None:
    manufacturing_writeup = summary.get("manufacturing_writeup", {})
    estimate_summary = summary.get("estimate_summary", {})
    document_analysis = summary.get("document_analysis", {})
    parts = manufacturing_writeup.get("parts", [])

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


def scan_file(pdf_path: Path) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    skip_vision = os.getenv("SKIP_VISION_EXTRACTION", "").lower() in {"1", "true", "yes"}
    started = time.time()

    def _debug(stage: str) -> None:
        if debug:
            elapsed = round(time.time() - started, 2)
            print(f"[DEBUG] {stage} (+{elapsed}s)")

    _debug("start extract_with_pdfplumber")
    plumber_pages = extract_with_pdfplumber(pdf_path)
    _debug("done extract_with_pdfplumber")

    _debug("start extract_with_pypdf")
    pypdf_pages = extract_with_pypdf(pdf_path)
    _debug("done extract_with_pypdf")

    if skip_vision:
        vision_pages = []
        _debug("skip extract_document_vision (SKIP_VISION_EXTRACTION=1)")
    else:
        _debug("start extract_document_vision")
        vision_pages = extract_document_vision(pdf_path)
        _debug("done extract_document_vision")

    _debug("start summarise_document")
    summary = summarise_document(pdf_path, plumber_pages, pypdf_pages, vision_pages=vision_pages)
    _debug("done summarise_document")
    _debug("start analyse_document_geometry")
    geometry_pages = analyse_document_geometry(pdf_path)
    _debug("done analyse_document_geometry")
    _debug("start calibrate_document_geometry")
    geometry_pages = calibrate_document_geometry(summary, geometry_pages)
    _debug("done calibrate_document_geometry")
    _debug("start merge_page_analysis")
    summary = merge_page_analysis(summary, geometry_pages)
    _debug("done merge_page_analysis")
    _debug("start build_document_writeup")
    summary["manufacturing_writeup"] = build_document_writeup(summary)
    _debug("done build_document_writeup")
    _debug("start estimate_document")
    summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"])
    _debug("done estimate_document")
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
