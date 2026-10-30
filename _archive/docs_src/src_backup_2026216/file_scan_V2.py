import json
import re
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
from geometry_analysis import analyse_document_geometry


def list_input_files(search_root: Path = config.DRAWINGS_DIR, drawing_pattern: str = "*.pdf") -> List[Path]:
    if not search_root.exists():
        return []
    return sorted([path for path in search_root.glob(drawing_pattern) if path.suffix.lower() in config.SUPPORTED_EXTENSIONS])


def _zone_boxes(page_width: float, page_height: float) -> Dict[str, Tuple[float, float, float, float]]:
    return {
        "title_block": (page_width * 0.58, page_height * 0.72, page_width, page_height),
        "bom": (0.0, page_height * 0.55, page_width * 0.55, page_height),
        "notes": (page_width * 0.55, 0.0, page_width, page_height * 0.5),
        "revision": (page_width * 0.72, page_height * 0.55, page_width, page_height * 0.8),
    }


def _words_in_box(words: List[Dict[str, Any]], box: Tuple[float, float, float, float]) -> List[Dict[str, Any]]:
    x0, top, x1, bottom = box
    selected: List[Dict[str, Any]] = []
    for word in words:
        word_x0 = float(word.get("x0", 0.0))
        word_x1 = float(word.get("x1", 0.0))
        word_top = float(word.get("top", 0.0))
        word_bottom = float(word.get("bottom", 0.0))
        if word_x1 >= x0 and word_x0 <= x1 and word_bottom >= top and word_top <= bottom:
            selected.append(word)
    return selected


def _words_to_text(words: List[Dict[str, Any]]) -> str:
    ordered = sorted(words, key=lambda item: (round(float(item.get("top", 0.0)), 1), float(item.get("x0", 0.0))))
    return normalize_text(" ".join(str(item.get("text", "")) for item in ordered))


def _infer_page_role(page_text: str, bom_text: str, title_block_text: str) -> Dict[str, Any]:
    full_text = normalize_text(f"{page_text} {bom_text} {title_block_text}")
    part_numbers = re.findall(config.PART_NUMBER_PATTERN, full_text, flags=re.IGNORECASE)
    bom_row_count = len(re.findall(config.QTY_TABLE_ROW_PATTERN, full_text, flags=re.IGNORECASE))

    signals: List[str] = []
    primary_role = "detail"

    if bom_row_count > 0:
        signals.append("bom_rows_detected")
    if len(set(part_numbers)) > 1:
        signals.append("multiple_part_numbers_detected")
    if "ASSEMBLY" in full_text.upper():
        signals.append("assembly_text_detected")
    if "FLAT PATTERN" in full_text.upper():
        signals.append("flat_pattern_detected")

    if bom_row_count > 0 or len(set(part_numbers)) > 1 or "ASSEMBLY" in full_text.upper():
        primary_role = "assembly"
    elif "FLAT PATTERN" in full_text.upper() or "DETAIL" in full_text.upper():
        primary_role = "detail"

    return {
        "primary_role": primary_role,
        "signals": signals,
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


def summarise_document(pdf_path: Path, plumber_pages: List[Dict[str, Any]], pypdf_pages: List[str]) -> Dict[str, Any]:
    joined_text = "\n\n".join(page["text"] for page in plumber_pages if page["text"])
    joined_title_block = "\n\n".join(page["region_text"]["title_block"] for page in plumber_pages if page["region_text"]["title_block"])
    joined_bom = "\n\n".join(page["region_text"]["bom"] for page in plumber_pages if page["region_text"]["bom"])
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
            "page_images_dir": str(config.PAGE_IMAGES_DIR),
        },
        "pages": [],
    }

    for page in plumber_pages:
        page_text = page["text"]
        page_number = page["page_number"]
        page_analysis = build_textual_manufacturing_summary(
            page_text,
            title_block_text=page["region_text"]["title_block"],
            bom_text=page["region_text"]["bom"],
            notes_text=page["region_text"]["notes"],
            page_role_hint=page["page_role"]["primary_role"],
        )
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
                "labels_found": find_labels(page["region_text"]["title_block"] or page_text),
                "pattern_summary": extract_patterns(page_text),
                "page_analysis": page_analysis,
                "text_preview": page_text[:1000],
            }
        )

    return summary


def write_outputs(summary: Dict[str, Any]) -> Tuple[Path, Path, Path, Path]:
    stem = Path(summary["source_file"]).stem
    json_path = config.JSON_DIR / f"{stem}.json"
    text_path = config.TEXT_DIR / f"{stem}.txt"
    log_path = config.LOG_DIR / f"{stem}.log"
    csv_path = config.CSV_DIR / "part_estimate_inputs.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    with text_path.open("w", encoding="utf-8") as handle:
        handle.write(f"SOURCE FILE: {summary['source_file']}\n")
        handle.write(f"PAGE COUNT: {summary['page_count']}\n")
        handle.write(f"DETECTED LABELS: {', '.join(summary['detected_labels'])}\n")
        handle.write(f"PART NUMBERS: {', '.join(summary['pattern_summary']['part_numbers'])}\n")
        handle.write(f"DATES: {', '.join(summary['pattern_summary']['dates'])}\n\n")

        handle.write("=" * 80 + "\nDOCUMENT ANALYSIS\n" + "=" * 80 + "\n")
        handle.write(json.dumps(summary.get("document_analysis", {}), indent=2, ensure_ascii=False))
        handle.write("\n\n")

        handle.write("=" * 80 + "\nMANUFACTURING WRITE-UP\n" + "=" * 80 + "\n")
        handle.write(json.dumps(summary.get("manufacturing_writeup", {}), indent=2, ensure_ascii=False))
        handle.write("\n\n")

        handle.write("=" * 80 + "\nESTIMATE SUMMARY\n" + "=" * 80 + "\n")
        handle.write(json.dumps(summary.get("estimate_summary", {}), indent=2, ensure_ascii=False))
        handle.write("\n\n")

        for page in summary["pages"]:
            handle.write("=" * 80 + "\n")
            handle.write(f"PAGE {page['page_number']}\n")
            handle.write("=" * 80 + "\n")
            handle.write("ROLE: " + page.get("page_role", {}).get("primary_role", "unknown") + "\n")
            handle.write("LABELS FOUND: " + ", ".join(page["labels_found"]) + "\n")
            handle.write("PATTERNS: " + json.dumps(page["pattern_summary"], ensure_ascii=False) + "\n")
            handle.write("REGIONS: " + json.dumps(page.get("region_text", {}), ensure_ascii=False) + "\n")
            handle.write("PAGE ANALYSIS: " + json.dumps(page.get("page_analysis", {}), ensure_ascii=False) + "\n")
            handle.write("GEOMETRY: " + json.dumps(page.get("geometry_summary", {}), ensure_ascii=False) + "\n\n")
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

    append_rows_to_csv(csv_path, build_estimate_input_rows(summary))
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
