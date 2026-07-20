import json
import re
from datetime import datetime
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from config import (
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


def list_input_files():
    return sorted(
        [p for p in DRAWINGS_DIR.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    )


def extract_with_pdfplumber(pdf_path: Path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            words = page.extract_words() or []
            pages.append(
                {
                    "page_number": idx,
                    "text": text,
                    "word_count": len(words),
                    "words": words,
                }
            )
    return pages


def extract_with_pypdf(pdf_path: Path):
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def find_labels(text: str):
    found = []
    upper_text = text.upper()
    for label in TITLE_BLOCK_LABELS:
        if label in upper_text:
            found.append(label)
    return found


def extract_patterns(text: str):
    return {
        "part_numbers": sorted(set(re.findall(PART_NUMBER_PATTERN, text))),
        "dates": sorted(set(re.findall(DATE_PATTERN, text))),
        "revision_matches": sorted(
            set(re.findall(REVISION_PATTERN, text, flags=re.IGNORECASE))
        ),
        "dimensions": sorted(set(re.findall(DIMENSION_PATTERN, text)))[:200],
    }


def summarise_document(pdf_path: Path, plumber_pages, pypdf_pages):
    joined_text = "\n\n".join(page["text"] for page in plumber_pages if page["text"])
    return {
        "source_file": pdf_path.name,
        "full_path": str(pdf_path),
        "page_count": len(plumber_pages),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "detected_labels": find_labels(joined_text),
        "pattern_summary": extract_patterns(joined_text),
        "output_targets": {
            "json_dir": str(JSON_DIR),
            "log_dir": str(LOG_DIR),
            "text_dir": str(TEXT_DIR),
            "page_images_dir": str(PAGE_IMAGES_DIR),
        },
        "pages": [
            {
                "page_number": p["page_number"],
                "pdfplumber_text": p["text"],
                "pypdf_text": pypdf_pages[p["page_number"] - 1]
                if p["page_number"] - 1 < len(pypdf_pages)
                else "",
                "word_count": p["word_count"],
                "labels_found": find_labels(p["text"]),
                "pattern_summary": extract_patterns(p["text"]),
            }
            for p in plumber_pages
        ],
    }


def write_outputs(summary: dict):
    stem = Path(summary["source_file"]).stem
    json_path = JSON_DIR / f"{stem}.json"
    text_path = TEXT_DIR / f"{stem}.txt"
    log_path = LOG_DIR / f"{stem}.log"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    with open(text_path, "w", encoding="utf-8") as f:
        f.write(f"SOURCE FILE: {summary['source_file']}\n")
        f.write(f"PAGE COUNT: {summary['page_count']}\n")
        f.write(f"DETECTED LABELS: {', '.join(summary['detected_labels'])}\n\n")

        for page in summary["pages"]:
            f.write("=" * 80 + "\n")
            f.write(f"PAGE {page['page_number']}\n")
            f.write("=" * 80 + "\n")
            f.write("LABELS FOUND: " + ", ".join(page["labels_found"]) + "\n")
            f.write("PATTERNS: " + json.dumps(page["pattern_summary"]) + "\n\n")
            f.write(page["pdfplumber_text"] or "[NO TEXT EXTRACTED]")
            f.write("\n\n")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "source_file": summary["source_file"],
                    "page_count": summary["page_count"],
                    "scanned_at": summary["scanned_at"],
                    "detected_labels": summary["detected_labels"],
                },
                indent=2,
            )
        )

    return json_path, text_path, log_path


def scan_file(pdf_path: Path):
    plumber_pages = extract_with_pdfplumber(pdf_path)
    pypdf_pages = extract_with_pypdf(pdf_path)
    summary = summarise_document(pdf_path, plumber_pages, pypdf_pages)
    output_paths = write_outputs(summary)
    return summary, output_paths