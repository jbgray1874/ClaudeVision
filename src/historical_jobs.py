import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config
from document_builder import build_document_writeup, merge_page_analysis
from estimator import estimate_document
from extractor_patterns import normalize_text
from file_scan import (
    extract_pdf_metadata,
    extract_patterns,
    extract_with_pdfplumber,
    extract_with_pypdf,
    summarise_document,
)
from geometry_analysis import analyse_document_geometry
from rag_transformer import transform_scan_summary_to_historical_job_record

try:
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover
    pd = None


def _normalize_job_key(value: str) -> str:
    stem = Path(value).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = re.sub(r"-+", "-", stem).strip("-")
    return stem


def list_history_files(history_root: Path = config.HISTORY_DIR) -> Dict[str, List[Path]]:
    drawings: List[Path] = []
    spreadsheets: List[Path] = []

    if not history_root.exists():
        return {"drawings": drawings, "spreadsheets": spreadsheets}

    for path in history_root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in config.SUPPORTED_EXTENSIONS:
            drawings.append(path)
        elif suffix in config.SPREADSHEET_EXTENSIONS:
            spreadsheets.append(path)

    return {
        "drawings": sorted(drawings),
        "spreadsheets": sorted(spreadsheets),
    }


def pair_history_files(history_root: Path = config.HISTORY_DIR) -> List[Dict[str, Any]]:
    files = list_history_files(history_root)
    jobs: Dict[str, Dict[str, Any]] = {}

    for path in files["drawings"]:
        key = _normalize_job_key(path.name)
        jobs.setdefault(key, {"job_key": key, "drawings": [], "spreadsheets": []})
        jobs[key]["drawings"].append(path)

    for path in files["spreadsheets"]:
        key = _normalize_job_key(path.name)
        jobs.setdefault(key, {"job_key": key, "drawings": [], "spreadsheets": []})
        jobs[key]["spreadsheets"].append(path)

    return sorted(jobs.values(), key=lambda item: item["job_key"])


def _read_spreadsheet_frames(path: Path) -> Dict[str, Any]:
    if pd is None:
        return {"sheets": [], "text_blob": "", "numeric_total": None}

    suffix = path.suffix.lower()
    sheet_payloads: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    numeric_total = 0.0
    numeric_found = False

    try:
        if suffix in {".csv", ".tsv"}:
            separator = "\t" if suffix == ".tsv" else ","
            frame = pd.read_csv(path, sep=separator)
            frames = {"Sheet1": frame}
        else:
            frames = pd.read_excel(path, sheet_name=None)
    except Exception as exc:
        return {"sheets": [], "text_blob": "", "numeric_total": None, "read_error": str(exc)}

    for sheet_name, frame in frames.items():
        safe_frame = frame.fillna("")
        values = safe_frame.astype(str).values.tolist()
        flat_text = normalize_text(" ".join(" ".join(row) for row in values))
        text_parts.append(flat_text)

        numeric_frame = frame.select_dtypes(include=["number"])
        if not numeric_frame.empty:
            numeric_total += float(numeric_frame.sum(numeric_only=True).sum())
            numeric_found = True

        headers = [str(column) for column in frame.columns]
        sample_rows = values[:10]
        sheet_payloads.append(
            {
                "sheet_name": sheet_name,
                "headers": headers,
                "sample_rows": sample_rows,
                "row_count": int(len(frame.index)),
                "column_count": int(len(frame.columns)),
            }
        )

    return {
        "sheets": sheet_payloads,
        "text_blob": normalize_text(" ".join(text_parts)),
        "numeric_total": round(numeric_total, 2) if numeric_found else None,
    }


def analyse_spreadsheet(path: Path) -> Dict[str, Any]:
    payload = _read_spreadsheet_frames(path)
    text_blob = payload.get("text_blob", "")
    return {
        "file_name": path.name,
        "file_path": str(path),
        "sheet_summaries": payload.get("sheets", []),
        "numeric_total": payload.get("numeric_total"),
        "text_blob": text_blob,
        "pattern_summary": extract_patterns(text_blob),
        "read_error": payload.get("read_error"),
    }


def analyse_historical_drawing(pdf_path: Path) -> Dict[str, Any]:
    plumber_pages = extract_with_pdfplumber(pdf_path)
    pypdf_pages = extract_with_pypdf(pdf_path)
    summary = summarise_document(pdf_path, plumber_pages, pypdf_pages)
    geometry_pages = analyse_document_geometry(pdf_path)
    summary = merge_page_analysis(summary, geometry_pages)
    summary["manufacturing_writeup"] = build_document_writeup(summary)
    summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"])
    summary["pdf_metadata"] = extract_pdf_metadata(pdf_path)
    return summary


def build_retrieval_record(job: Dict[str, Any]) -> Dict[str, Any]:
    spreadsheet_analyses = [analyse_spreadsheet(path) for path in job.get("spreadsheets", [])]
    drawing_analyses = [analyse_historical_drawing(path) for path in job.get("drawings", [])]
    primary_spreadsheet = spreadsheet_analyses[0] if spreadsheet_analyses else None
    transformed_drawings = [
        transform_scan_summary_to_historical_job_record(
            drawing,
            spreadsheet_analysis=primary_spreadsheet,
            job_key=job["job_key"],
        )
        for drawing in drawing_analyses
    ]

    if transformed_drawings:
        base_record = transformed_drawings[0]
    else:
        base_record = {
            "schema_version": "historical_job_record.v1",
            "job_key": job["job_key"],
            "document": {},
            "parts": [],
            "spreadsheet_context": primary_spreadsheet,
            "retrieval_fields": {
                "part_numbers": [],
                "materials": [],
                "thicknesses_mm": [],
                "operations": [],
                "estimated_total_cost_gbp": None,
                "surface_finishes": [],
            },
            "retrieval_text": "",
        }

    spreadsheet_numeric_total = next(
        (item.get("numeric_total") for item in spreadsheet_analyses if item.get("numeric_total") is not None),
        None,
    )
    base_record["spreadsheet_files"] = [str(path) for path in job.get("spreadsheets", [])]
    base_record["drawing_files"] = [str(path) for path in job.get("drawings", [])]
    base_record["spreadsheet_analyses"] = spreadsheet_analyses
    base_record["drawing_analyses"] = drawing_analyses
    base_record["retrieval_fields"]["spreadsheet_numeric_total"] = spreadsheet_numeric_total
    if primary_spreadsheet and not base_record.get("retrieval_text"):
        base_record["retrieval_text"] = normalize_text(primary_spreadsheet.get("text_blob", ""))[:12000]
    return base_record


def build_history_corpus(history_root: Path = config.HISTORY_DIR) -> Dict[str, Any]:
    config.ensure_directories()
    jobs = pair_history_files(history_root)
    records = [build_retrieval_record(job) for job in jobs if job.get("drawings") or job.get("spreadsheets")]

    json_path = config.HISTORY_JSON_DIR / "historical_jobs_corpus.json"
    csv_path = config.HISTORY_CSV_DIR / "historical_jobs_corpus.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump({"history_root": str(history_root), "records": records}, handle, indent=2, ensure_ascii=False)

    rows: List[Dict[str, Any]] = []
    for record in records:
        retrieval = record["retrieval_fields"]
        rows.append(
            {
                "job_key": record["job_key"],
                "spreadsheet_file": "; ".join(record["spreadsheet_files"]),
                "drawing_file": "; ".join(record["drawing_files"]),
                "part_numbers": "; ".join(retrieval.get("part_numbers", [])),
                "materials": "; ".join(retrieval.get("materials", [])),
                "thicknesses_mm": "; ".join(retrieval.get("thicknesses_mm", [])),
                "operations": "; ".join(retrieval.get("operations", [])),
                "estimated_total_cost_gbp": retrieval.get("estimated_total_cost_gbp"),
                "document_total_estimated_cost_gbp": retrieval.get("estimated_total_cost_gbp"),
                "spreadsheet_numeric_total": retrieval.get("spreadsheet_numeric_total"),
                "text_snippet": record["retrieval_text"][:500],
            }
        )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=config.HISTORY_CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "history_root": str(history_root),
        "job_count": len(records),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
    }
