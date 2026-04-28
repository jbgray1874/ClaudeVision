import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config


def _sql_quote(value: Optional[str]) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _sql_text(value: Any) -> str:
    if value is None:
        return "NULL"
    return _sql_quote(str(value))


def _sql_int(value: Any) -> str:
    if value in (None, ""):
        return "NULL"
    return str(int(value))


def _sql_numeric(value: Any) -> str:
    if value in (None, ""):
        return "NULL"
    return str(value)


def _jsonb(value: Any) -> str:
    payload = json.dumps(value if value is not None else {}, ensure_ascii=False)
    return f"CAST({_sql_quote(payload)} AS jsonb)"


def next_run_version(source_file_name: str, archive_json_dir: Path = config.ARCHIVE_JSON_DIR) -> int:
    stem = Path(source_file_name).stem
    archive_count = sum(1 for _ in archive_json_dir.glob(f"{stem}_*.json"))
    return archive_count + 1


def version_label(version_number: int) -> str:
    return f"v{version_number:04d}"


def build_run_metadata(
    summary: Dict[str, Any],
    archive_json_dir: Path = config.ARCHIVE_JSON_DIR,
    source_json_path: Optional[Path] = None,
) -> Dict[str, Any]:
    existing = summary.get("run_metadata")
    if isinstance(existing, dict) and existing.get("run_uuid") and existing.get("source_file_version"):
        return existing

    source_file = summary.get("source_file", "")
    scanned_at = summary.get("scanned_at", "")
    stem = Path(source_file).stem if source_file else "scan"

    version_number = 1
    if source_json_path is None:
        version_number = next_run_version(source_file, archive_json_dir=archive_json_dir)
    else:
        match = re.search(r"_v(\d{4})_", source_json_path.name, flags=re.IGNORECASE)
        if match:
            version_number = int(match.group(1))

    label = version_label(version_number)
    run_uuid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{source_file}|{scanned_at}|{source_json_path or summary.get('full_path', '')}|{version_number}",
        )
    )

    metadata = {
        "run_uuid": run_uuid,
        "source_file_stem": stem,
        "source_file_version": version_number,
        "source_file_version_label": label,
        "source_file_versioned_name": f"{stem}_{label}{Path(source_file).suffix or '.pdf'}",
        "database_schema_version": "drawing_scan_store.v1",
    }
    summary["run_metadata"] = metadata
    return metadata


def _validation_status(summary: Dict[str, Any]) -> Optional[str]:
    return summary.get("manufacturing_writeup", {}).get("validation", {}).get("status")


def _page_insert_sql(run_uuid: str, page: Dict[str, Any]) -> str:
    return f"""INSERT INTO drawing_page (
    run_uuid,
    page_number,
    page_role,
    word_count,
    page_width,
    page_height,
    labels_found,
    pattern_summary,
    title_block_calibration,
    region_text,
    page_analysis,
    geometry_summary,
    text_preview
) VALUES (
    {_sql_quote(run_uuid)},
    {_sql_int(page.get("page_number"))},
    {_sql_text(page.get("page_role", {}).get("primary_role"))},
    {_sql_int(page.get("word_count"))},
    {_sql_numeric(page.get("page_width"))},
    {_sql_numeric(page.get("page_height"))},
    {_jsonb(page.get("labels_found", []))},
    {_jsonb(page.get("pattern_summary", {}))},
    {_jsonb(page.get("title_block_calibration", {}))},
    {_jsonb(page.get("region_text", {}))},
    {_jsonb(page.get("page_analysis", {}))},
    {_jsonb(page.get("geometry_summary", {}))},
    {_sql_text(page.get("text_preview"))}
)
ON CONFLICT (run_uuid, page_number) DO UPDATE SET
    page_role = EXCLUDED.page_role,
    word_count = EXCLUDED.word_count,
    page_width = EXCLUDED.page_width,
    page_height = EXCLUDED.page_height,
    labels_found = EXCLUDED.labels_found,
    pattern_summary = EXCLUDED.pattern_summary,
    title_block_calibration = EXCLUDED.title_block_calibration,
    region_text = EXCLUDED.region_text,
    page_analysis = EXCLUDED.page_analysis,
    geometry_summary = EXCLUDED.geometry_summary,
    text_preview = EXCLUDED.text_preview;"""


def _part_insert_sql(run_uuid: str, part: Dict[str, Any]) -> str:
    return f"""INSERT INTO drawing_part (
    run_uuid,
    part_number,
    item_number,
    description,
    quantity,
    page_roles,
    pages,
    materials,
    surface_finishes,
    colours,
    revisions,
    drawing_numbers,
    thicknesses_mm,
    dimensions_mm,
    angles_deg,
    hole_sizes_mm,
    slot_sizes_mm,
    process_notes,
    operations,
    manufacturing_features,
    manufacturing_interpretation,
    geometry_rollup,
    part_json
) VALUES (
    {_sql_quote(run_uuid)},
    {_sql_text(part.get("part_number"))},
    {_sql_text(part.get("item_number"))},
    {_sql_text(part.get("description"))},
    {_sql_int(part.get("quantity"))},
    {_jsonb(part.get("page_roles", []))},
    {_jsonb(part.get("pages", []))},
    {_jsonb(part.get("materials", []))},
    {_jsonb(part.get("surface_finishes", []))},
    {_jsonb(part.get("colours", []))},
    {_jsonb(part.get("revisions", []))},
    {_jsonb(part.get("drawing_numbers", []))},
    {_jsonb(part.get("thicknesses_mm", []))},
    {_jsonb(part.get("all_dimensions_mm", []))},
    {_jsonb(part.get("angles_deg", []))},
    {_jsonb(part.get("hole_sizes_mm", []))},
    {_jsonb(part.get("slot_sizes_mm", []))},
    {_jsonb(part.get("process_notes", []))},
    {_jsonb(part.get("textual_operations", []))},
    {_jsonb(part.get("manufacturing_features", {}))},
    {_jsonb(part.get("manufacturing_interpretation", {}))},
    {_jsonb(part.get("geometry_rollup", {}))},
    {_jsonb(part)}
)
ON CONFLICT (run_uuid, part_number) DO UPDATE SET
    item_number = EXCLUDED.item_number,
    description = EXCLUDED.description,
    quantity = EXCLUDED.quantity,
    page_roles = EXCLUDED.page_roles,
    pages = EXCLUDED.pages,
    materials = EXCLUDED.materials,
    surface_finishes = EXCLUDED.surface_finishes,
    colours = EXCLUDED.colours,
    revisions = EXCLUDED.revisions,
    drawing_numbers = EXCLUDED.drawing_numbers,
    thicknesses_mm = EXCLUDED.thicknesses_mm,
    dimensions_mm = EXCLUDED.dimensions_mm,
    angles_deg = EXCLUDED.angles_deg,
    hole_sizes_mm = EXCLUDED.hole_sizes_mm,
    slot_sizes_mm = EXCLUDED.slot_sizes_mm,
    process_notes = EXCLUDED.process_notes,
    operations = EXCLUDED.operations,
    manufacturing_features = EXCLUDED.manufacturing_features,
    manufacturing_interpretation = EXCLUDED.manufacturing_interpretation,
    geometry_rollup = EXCLUDED.geometry_rollup,
    part_json = EXCLUDED.part_json;"""


def generate_postgres_insert_sql(summary: Dict[str, Any], source_json_path: Optional[Path] = None) -> str:
    metadata = build_run_metadata(summary, source_json_path=source_json_path)
    run_uuid = metadata["run_uuid"]
    title_block = summary.get("document_analysis", {}).get("title_block", {})

    statements: List[str] = [
        "BEGIN;",
        f"""INSERT INTO drawing_scan_run (
    run_uuid,
    source_file_name,
    source_file_stem,
    source_file_version,
    source_file_version_label,
    source_file_versioned_name,
    source_pdf_path,
    scanned_at,
    page_count,
    validation_status,
    latest_json_path,
    archive_json_path,
    raw_summary_json
) VALUES (
    {_sql_quote(run_uuid)},
    {_sql_text(summary.get("source_file"))},
    {_sql_text(metadata.get("source_file_stem"))},
    {_sql_int(metadata.get("source_file_version"))},
    {_sql_text(metadata.get("source_file_version_label"))},
    {_sql_text(metadata.get("source_file_versioned_name"))},
    {_sql_text(summary.get("full_path"))},
    {_sql_text(summary.get("scanned_at"))},
    {_sql_int(summary.get("page_count"))},
    {_sql_text(_validation_status(summary))},
    {_sql_text(summary.get("saved_output_paths", {}).get("json"))},
    {_sql_text(summary.get("archived_output_paths", {}).get("json"))},
    {_jsonb(summary)}
)
ON CONFLICT (run_uuid) DO UPDATE SET
    source_file_name = EXCLUDED.source_file_name,
    source_file_stem = EXCLUDED.source_file_stem,
    source_file_version = EXCLUDED.source_file_version,
    source_file_version_label = EXCLUDED.source_file_version_label,
    source_file_versioned_name = EXCLUDED.source_file_versioned_name,
    source_pdf_path = EXCLUDED.source_pdf_path,
    scanned_at = EXCLUDED.scanned_at,
    page_count = EXCLUDED.page_count,
    validation_status = EXCLUDED.validation_status,
    latest_json_path = EXCLUDED.latest_json_path,
    archive_json_path = EXCLUDED.archive_json_path,
    raw_summary_json = EXCLUDED.raw_summary_json;""",
        f"""INSERT INTO drawing_document (
    run_uuid,
    source_file_name,
    drawing_numbers,
    revisions,
    dates,
    materials,
    surface_finishes,
    colours,
    detected_labels,
    pattern_summary,
    title_block,
    bom_rows,
    dimensions,
    feature_cues,
    document_analysis,
    manufacturing_writeup,
    estimate_summary,
    validation,
    pdf_metadata
) VALUES (
    {_sql_quote(run_uuid)},
    {_sql_text(summary.get("source_file"))},
    {_jsonb(title_block.get("drawing_numbers", []))},
    {_jsonb(title_block.get("revisions", []))},
    {_jsonb(title_block.get("dates", []))},
    {_jsonb(title_block.get("materials", []))},
    {_jsonb(title_block.get("surface_finishes", []))},
    {_jsonb(title_block.get("colours", []))},
    {_jsonb(summary.get("detected_labels", []))},
    {_jsonb(summary.get("pattern_summary", {}))},
    {_jsonb(title_block)},
    {_jsonb(summary.get("document_analysis", {}).get("bom_rows", []))},
    {_jsonb(summary.get("document_analysis", {}).get("dimensions", {}))},
    {_jsonb(summary.get("document_analysis", {}).get("feature_cues", {}))},
    {_jsonb(summary.get("document_analysis", {}))},
    {_jsonb(summary.get("manufacturing_writeup", {}))},
    {_jsonb(summary.get("estimate_summary", {}))},
    {_jsonb(summary.get("manufacturing_writeup", {}).get("validation", {}))},
    {_jsonb(summary.get("pdf_metadata", {}))}
)
ON CONFLICT (run_uuid) DO UPDATE SET
    source_file_name = EXCLUDED.source_file_name,
    drawing_numbers = EXCLUDED.drawing_numbers,
    revisions = EXCLUDED.revisions,
    dates = EXCLUDED.dates,
    materials = EXCLUDED.materials,
    surface_finishes = EXCLUDED.surface_finishes,
    colours = EXCLUDED.colours,
    detected_labels = EXCLUDED.detected_labels,
    pattern_summary = EXCLUDED.pattern_summary,
    title_block = EXCLUDED.title_block,
    bom_rows = EXCLUDED.bom_rows,
    dimensions = EXCLUDED.dimensions,
    feature_cues = EXCLUDED.feature_cues,
    document_analysis = EXCLUDED.document_analysis,
    manufacturing_writeup = EXCLUDED.manufacturing_writeup,
    estimate_summary = EXCLUDED.estimate_summary,
    validation = EXCLUDED.validation,
    pdf_metadata = EXCLUDED.pdf_metadata;""",
    ]

    for page in summary.get("pages", []):
        statements.append(_page_insert_sql(run_uuid, page))

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        statements.append(_part_insert_sql(run_uuid, part))

    statements.append("COMMIT;")
    return "\n\n".join(statements) + "\n"


def write_postgres_insert_sql(summary: Dict[str, Any], sql_path: Path) -> Path:
    sql_path.write_text(generate_postgres_insert_sql(summary), encoding="utf-8")
    return sql_path


def export_json_files_to_postgres_sql(json_paths: Iterable[Path], output_sql_path: Path) -> Path:
    statements: List[str] = [
        "-- Generated from scan JSON files.",
        "-- Assumes the PostgreSQL schema in sql/postgres_scan_store.sql has already been run.",
    ]
    for json_path in json_paths:
        with json_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
        statements.append(generate_postgres_insert_sql(summary, source_json_path=json_path))
    output_sql_path.write_text("\n".join(statements), encoding="utf-8")
    return output_sql_path
