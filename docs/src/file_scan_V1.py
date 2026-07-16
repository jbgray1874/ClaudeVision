import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pdfplumber
from pypdf import PdfReader

from config import (
    CSV_DIR,
    DATE_PATTERN,
    DIMENSION_PATTERN,
    DRAWINGS_DIR,
    JSON_DIR,
    LOG_DIR,
    PAGE_IMAGES_DIR,
    PART_NUMBER_PATTERN,
    REVISION_PATTERN,
    SUPPORTED_EXTENSIONS,
    TEXT_DIR,
    TITLE_BLOCK_LABELS,
)
from document_builder import build_document_writeup, merge_page_analysis
from estimator import estimate_document
from extractor_patterns import build_textual_manufacturing_summary, normalize_text
from geometry_analysis import analyse_document_geometry


CSV_HEADERS = [
    "source_file",
    "part_number",
    "description",
    "quantity",
    "material",
    "thickness_mm",
    "finish",
    "colour",
    "revision",
    "dates",
    "dimensions_mm",
    "angles_deg",
    "hole_sizes_mm",
    "operations",
    "estimated_cut_length_mm",
    "estimated_hole_count",
    "estimated_bend_line_count",
    "blank_length_mm",
    "blank_width_mm",
    "material_cost_gbp",
    "total_time_min",
    "total_labour_cost_gbp",
    "estimated_total_cost_gbp",
]



def list_input_files(search_root: Path = DRAWINGS_DIR, drawing_pattern: str = "*.pdf") -> List[Path]:
    if not search_root.exists():
        return []
    return sorted([p for p in search_root.glob(drawing_pattern) if p.suffix.lower() in SUPPORTED_EXTENSIONS])



def extract_with_pdfplumber(pdf_path: Path) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            words = page.extract_words() or []
            pages.append(
                {
                    "page_number": idx,
                    "text": text,
                    "normalized_text": normalize_text(text),
                    "word_count": len(words),
                    "words": words,
                    "page_width": page.width,
                    "page_height": page.height,
                }
            )
    return pages



def extract_with_pypdf(pdf_path: Path) -> List[str]:
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]



def extract_pdf_metadata(pdf_path: Path) -> Dict[str, Any]:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata or {}
        return {str(key): str(value) for key, value in metadata.items()}
    except Exception:
        return {}



def find_labels(text: str) -> List[str]:
    found: List[str] = []
    upper_text = (text or "").upper()
    for label in TITLE_BLOCK_LABELS:
        if label in upper_text:
            found.append(label)
    return found



def extract_patterns(text: str) -> Dict[str, Any]:
    return {
        "part_numbers": sorted(set(re.findall(PART_NUMBER_PATTERN, text, flags=re.IGNORECASE))),
        "dates": sorted(set(re.findall(DATE_PATTERN, text, flags=re.IGNORECASE))),
        "revision_matches": sorted(set(re.findall(REVISION_PATTERN, text, flags=re.IGNORECASE))),
        "dimensions_mm": sorted(set(re.findall(DIMENSION_PATTERN, text, flags=re.IGNORECASE)))[:500],
    }



def summarise_document(pdf_path: Path, plumber_pages: List[Dict[str, Any]], pypdf_pages: List[str]) -> Dict[str, Any]:
    joined_text = "\n\n".join(page["text"] for page in plumber_pages if page["text"])
    normalized_joined = normalize_text(joined_text)
    document_analysis = build_textual_manufacturing_summary(normalized_joined)

    summary: Dict[str, Any] = {
        "source_file": pdf_path.name,
        "full_path": str(pdf_path),
        "page_count": len(plumber_pages),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_metadata": extract_pdf_metadata(pdf_path),
        "detected_labels": find_labels(normalized_joined),
        "pattern_summary": extract_patterns(normalized_joined),
        "document_analysis": document_analysis,
        "output_targets": {
            "json_dir": str(JSON_DIR),
            "log_dir": str(LOG_DIR),
            "text_dir": str(TEXT_DIR),
            "csv_dir": str(CSV_DIR),
            "page_images_dir": str(PAGE_IMAGES_DIR),
        },
        "pages": [],
    }

    for page in plumber_pages:
        page_text = page["text"]
        page_analysis = build_textual_manufacturing_summary(page_text)
        summary["pages"].append(
            {
                "page_number": page["page_number"],
                "pdfplumber_text": page_text,
                "normalized_text": page["normalized_text"],
                "pypdf_text": pypdf_pages[page["page_number"] - 1] if page["page_number"] - 1 < len(pypdf_pages) else "",
                "word_count": page["word_count"],
                "page_width": page["page_width"],
                "page_height": page["page_height"],
                "labels_found": find_labels(page_text),
                "pattern_summary": extract_patterns(page_text),
                "page_analysis": page_analysis,
            }
        )

    return summary



def build_master_csv_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    part_estimates_lookup = {
        item["part_number"]: item for item in summary.get("estimate_summary", {}).get("part_estimates", [])
    }

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        estimate = part_estimates_lookup.get(part.get("part_number"), {})
        material_estimate = estimate.get("material_estimate", {})
        process_estimate = estimate.get("process_estimate", {})
        labour_estimate = estimate.get("labour_estimate", {})
        rows.append(
            {
                "source_file": summary["source_file"],
                "part_number": part.get("part_number"),
                "description": part.get("description"),
                "quantity": part.get("quantity"),
                "material": "; ".join(part.get("materials", [])),
                "thickness_mm": "; ".join([str(v) for v in part.get("thicknesses_mm", [])]),
                "finish": "; ".join(part.get("surface_finishes", [])),
                "colour": "; ".join(part.get("colours", [])),
                "revision": "; ".join(part.get("revisions", [])),
                "dates": "; ".join(part.get("dates", [])),
                "dimensions_mm": "; ".join([str(v) for v in part.get("all_dimensions_mm", [])]),
                "angles_deg": "; ".join([str(v) for v in part.get("angles_deg", [])]),
                "hole_sizes_mm": "; ".join([str(v) for v in part.get("hole_sizes_mm", [])]),
                "operations": "; ".join(part.get("textual_operations", [])),
                "estimated_cut_length_mm": process_estimate.get("cut_length_mm"),
                "estimated_hole_count": process_estimate.get("hole_count"),
                "estimated_bend_line_count": process_estimate.get("bend_count"),
                "blank_length_mm": material_estimate.get("blank_length_mm"),
                "blank_width_mm": material_estimate.get("blank_width_mm"),
                "material_cost_gbp": material_estimate.get("material_cost_gbp"),
                "total_time_min": process_estimate.get("total_time_min"),
                "total_labour_cost_gbp": labour_estimate.get("total_labour_cost_gbp"),
                "estimated_total_cost_gbp": estimate.get("estimated_total_cost_gbp"),
            }
        )
    return rows



def append_rows_to_csv(csv_path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)



def write_outputs(summary: Dict[str, Any]) -> Tuple[Path, Path, Path, Path]:
    stem = Path(summary["source_file"]).stem
    json_path = JSON_DIR / f"{stem}.json"
    text_path = TEXT_DIR / f"{stem}.txt"
    log_path = LOG_DIR / f"{stem}.log"
    csv_path = CSV_DIR / "part_estimate_inputs.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    with text_path.open("w", encoding="utf-8") as handle:
        handle.write(f"SOURCE FILE: {summary['source_file']}\n")
        handle.write(f"PAGE COUNT: {summary['page_count']}\n")
        handle.write(f"DETECTED LABELS: {', '.join(summary['detected_labels'])}\n")
        handle.write(f"PART NUMBERS: {', '.join(summary['pattern_summary']['part_numbers'])}\n")
        handle.write(f"DATES: {', '.join(summary['pattern_summary']['dates'])}\n\n")

        handle.write("=" * 80 + "\n")
        handle.write("DOCUMENT ANALYSIS\n")
        handle.write("=" * 80 + "\n")
        handle.write(json.dumps(summary.get("document_analysis", {}), indent=2))
        handle.write("\n\n")

        handle.write("=" * 80 + "\n")
        handle.write("MANUFACTURING WRITE-UP\n")
        handle.write("=" * 80 + "\n")
        handle.write(json.dumps(summary.get("manufacturing_writeup", {}), indent=2))
        handle.write("\n\n")

        handle.write("=" * 80 + "\n")
        handle.write("ESTIMATE SUMMARY\n")
        handle.write("=" * 80 + "\n")
        handle.write(json.dumps(summary.get("estimate_summary", {}), indent=2))
        handle.write("\n\n")

        for page in summary["pages"]:
            handle.write("=" * 80 + "\n")
            handle.write(f"PAGE {page['page_number']}\n")
            handle.write("=" * 80 + "\n")
            handle.write("LABELS FOUND: " + ", ".join(page["labels_found"]) + "\n")
            handle.write("PATTERNS: " + json.dumps(page["pattern_summary"]) + "\n")
            handle.write("PAGE ANALYSIS: " + json.dumps(page.get("page_analysis", {})) + "\n")
            handle.write("GEOMETRY: " + json.dumps(page.get("geometry_summary", {})) + "\n\n")
            handle.write(page["pdfplumber_text"] or "[NO TEXT EXTRACTED]")
            handle.write("\n\n")

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "source_file": summary["source_file"],
                    "page_count": summary["page_count"],
                    "scanned_at": summary["scanned_at"],
                    "detected_labels": summary["detected_labels"],
                    "part_numbers": summary["pattern_summary"]["part_numbers"],
                    "output_csv": str(csv_path),
                },
                indent=2,
            )
        )

    append_rows_to_csv(csv_path, build_master_csv_rows(summary))
    return json_path, text_path, log_path, csv_path



def scan_file(pdf_path: Path) -> Tuple[Dict[str, Any], Tuple[Path, Path, Path, Path]]:
    plumber_pages = extract_with_pdfplumber(pdf_path)
    pypdf_pages = extract_with_pypdf(pdf_path)

    summary = summarise_document(pdf_path, plumber_pages, pypdf_pages)
    geometry_pages = analyse_document_geometry(pdf_path)
    summary = merge_page_analysis(summary, geometry_pages)
    summary["manufacturing_writeup"] = build_document_writeup(summary)
    summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"])

    output_paths = write_outputs(summary)
    return summary, output_paths
