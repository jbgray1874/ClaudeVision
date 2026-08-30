import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config


def _sql_quote(value: Optional[str]) -> str:
    if value is None:
        return "NULL"
    return "N'" + str(value).replace("'", "''") + "'"


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


def _json_text(value: Any) -> str:
    payload = json.dumps(value if value is not None else {}, ensure_ascii=False)
    return _sql_quote(payload)


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
        "database_schema_version": "drawing_scan_store.sqlserver.v1",
    }
    summary["run_metadata"] = metadata
    return metadata


def _validation_status(summary: Dict[str, Any]) -> Optional[str]:
    return summary.get("manufacturing_writeup", {}).get("validation", {}).get("status")


def _page_merge_sql(run_uuid: str, page: Dict[str, Any]) -> str:
    return f"""MERGE INTO dbo.drawing_page AS target
USING (
    SELECT
        CAST({_sql_quote(run_uuid)} AS uniqueidentifier) AS run_uuid,
        {_sql_int(page.get("page_number"))} AS page_number,
        {_sql_text(page.get("page_role", {}).get("primary_role"))} AS page_role,
        {_sql_int(page.get("word_count"))} AS word_count,
        {_sql_numeric(page.get("page_width"))} AS page_width,
        {_sql_numeric(page.get("page_height"))} AS page_height,
        {_json_text(page.get("labels_found", []))} AS labels_found,
        {_json_text(page.get("pattern_summary", {}))} AS pattern_summary,
        {_json_text(page.get("title_block_calibration", {}))} AS title_block_calibration,
        {_json_text(page.get("region_text", {}))} AS region_text,
        {_json_text(page.get("page_analysis", {}))} AS page_analysis,
        {_json_text(page.get("geometry_summary", {}))} AS geometry_summary,
        {_sql_text(page.get("text_preview"))} AS text_preview
) AS source
ON target.run_uuid = source.run_uuid AND target.page_number = source.page_number
WHEN MATCHED THEN
    UPDATE SET
        page_role = source.page_role,
        word_count = source.word_count,
        page_width = source.page_width,
        page_height = source.page_height,
        labels_found = source.labels_found,
        pattern_summary = source.pattern_summary,
        title_block_calibration = source.title_block_calibration,
        region_text = source.region_text,
        page_analysis = source.page_analysis,
        geometry_summary = source.geometry_summary,
        text_preview = source.text_preview
WHEN NOT MATCHED THEN
    INSERT (
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
    )
    VALUES (
        source.run_uuid,
        source.page_number,
        source.page_role,
        source.word_count,
        source.page_width,
        source.page_height,
        source.labels_found,
        source.pattern_summary,
        source.title_block_calibration,
        source.region_text,
        source.page_analysis,
        source.geometry_summary,
        source.text_preview
    );"""


def _part_merge_sql(run_uuid: str, part: Dict[str, Any]) -> str:
    return f"""MERGE INTO dbo.drawing_part AS target
USING (
    SELECT
        CAST({_sql_quote(run_uuid)} AS uniqueidentifier) AS run_uuid,
        {_sql_text(part.get("part_number"))} AS part_number,
        {_sql_text(part.get("item_number"))} AS item_number,
        {_sql_text(part.get("description"))} AS description,
        {_sql_int(part.get("quantity"))} AS quantity,
        {_json_text(part.get("page_roles", []))} AS page_roles,
        {_json_text(part.get("pages", []))} AS pages,
        {_json_text(part.get("materials", []))} AS materials,
        {_json_text(part.get("surface_finishes", []))} AS surface_finishes,
        {_json_text(part.get("colours", []))} AS colours,
        {_json_text(part.get("revisions", []))} AS revisions,
        {_json_text(part.get("drawing_numbers", []))} AS drawing_numbers,
        {_json_text(part.get("thicknesses_mm", []))} AS thicknesses_mm,
        {_json_text(part.get("all_dimensions_mm", []))} AS dimensions_mm,
        {_json_text(part.get("angles_deg", []))} AS angles_deg,
        {_json_text(part.get("hole_sizes_mm", []))} AS hole_sizes_mm,
        {_json_text(part.get("slot_sizes_mm", []))} AS slot_sizes_mm,
        {_json_text(part.get("process_notes", []))} AS process_notes,
        {_json_text(part.get("textual_operations", []))} AS operations,
        {_json_text(part.get("manufacturing_features", {}))} AS manufacturing_features,
        {_json_text(part.get("manufacturing_interpretation", {}))} AS manufacturing_interpretation,
        {_json_text(part.get("geometry_rollup", {}))} AS geometry_rollup,
        {_json_text(part)} AS part_json
) AS source
ON target.run_uuid = source.run_uuid AND target.part_number = source.part_number
WHEN MATCHED THEN
    UPDATE SET
        item_number = source.item_number,
        description = source.description,
        quantity = source.quantity,
        page_roles = source.page_roles,
        pages = source.pages,
        materials = source.materials,
        surface_finishes = source.surface_finishes,
        colours = source.colours,
        revisions = source.revisions,
        drawing_numbers = source.drawing_numbers,
        thicknesses_mm = source.thicknesses_mm,
        dimensions_mm = source.dimensions_mm,
        angles_deg = source.angles_deg,
        hole_sizes_mm = source.hole_sizes_mm,
        slot_sizes_mm = source.slot_sizes_mm,
        process_notes = source.process_notes,
        operations = source.operations,
        manufacturing_features = source.manufacturing_features,
        manufacturing_interpretation = source.manufacturing_interpretation,
        geometry_rollup = source.geometry_rollup,
        part_json = source.part_json
WHEN NOT MATCHED THEN
    INSERT (
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
    )
    VALUES (
        source.run_uuid,
        source.part_number,
        source.item_number,
        source.description,
        source.quantity,
        source.page_roles,
        source.pages,
        source.materials,
        source.surface_finishes,
        source.colours,
        source.revisions,
        source.drawing_numbers,
        source.thicknesses_mm,
        source.dimensions_mm,
        source.angles_deg,
        source.hole_sizes_mm,
        source.slot_sizes_mm,
        source.process_notes,
        source.operations,
        source.manufacturing_features,
        source.manufacturing_interpretation,
        source.geometry_rollup,
        source.part_json
    );"""


def generate_sqlserver_insert_sql(summary: Dict[str, Any], source_json_path: Optional[Path] = None) -> str:
    metadata = build_run_metadata(summary, source_json_path=source_json_path)
    run_uuid = metadata["run_uuid"]
    title_block = summary.get("document_analysis", {}).get("title_block", {})

    statements: List[str] = [
        "BEGIN TRANSACTION;",
        f"""MERGE INTO dbo.drawing_scan_run AS target
USING (
    SELECT
        CAST({_sql_quote(run_uuid)} AS uniqueidentifier) AS run_uuid,
        {_sql_text(summary.get("source_file"))} AS source_file_name,
        {_sql_text(metadata.get("source_file_stem"))} AS source_file_stem,
        {_sql_int(metadata.get("source_file_version"))} AS source_file_version,
        {_sql_text(metadata.get("source_file_version_label"))} AS source_file_version_label,
        {_sql_text(metadata.get("source_file_versioned_name"))} AS source_file_versioned_name,
        {_sql_text(summary.get("full_path"))} AS source_pdf_path,
        CAST({_sql_text(summary.get("scanned_at"))} AS datetime2) AS scanned_at,
        {_sql_int(summary.get("page_count"))} AS page_count,
        {_sql_text(_validation_status(summary))} AS validation_status,
        {_sql_text(summary.get("saved_output_paths", {}).get("json"))} AS latest_json_path,
        {_sql_text(summary.get("archived_output_paths", {}).get("json"))} AS archive_json_path,
        {_json_text(summary)} AS raw_summary_json
) AS source
ON target.run_uuid = source.run_uuid
WHEN MATCHED THEN
    UPDATE SET
        source_file_name = source.source_file_name,
        source_file_stem = source.source_file_stem,
        source_file_version = source.source_file_version,
        source_file_version_label = source.source_file_version_label,
        source_file_versioned_name = source.source_file_versioned_name,
        source_pdf_path = source.source_pdf_path,
        scanned_at = source.scanned_at,
        page_count = source.page_count,
        validation_status = source.validation_status,
        latest_json_path = source.latest_json_path,
        archive_json_path = source.archive_json_path,
        raw_summary_json = source.raw_summary_json
WHEN NOT MATCHED THEN
    INSERT (
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
    )
    VALUES (
        source.run_uuid,
        source.source_file_name,
        source.source_file_stem,
        source.source_file_version,
        source.source_file_version_label,
        source.source_file_versioned_name,
        source.source_pdf_path,
        source.scanned_at,
        source.page_count,
        source.validation_status,
        source.latest_json_path,
        source.archive_json_path,
        source.raw_summary_json
    );""",
        f"""MERGE INTO dbo.drawing_document AS target
USING (
    SELECT
        CAST({_sql_quote(run_uuid)} AS uniqueidentifier) AS run_uuid,
        {_sql_text(summary.get("source_file"))} AS source_file_name,
        {_json_text(title_block.get("drawing_numbers", []))} AS drawing_numbers,
        {_json_text(title_block.get("revisions", []))} AS revisions,
        {_json_text(title_block.get("dates", []))} AS dates,
        {_json_text(title_block.get("materials", []))} AS materials,
        {_json_text(title_block.get("surface_finishes", []))} AS surface_finishes,
        {_json_text(title_block.get("colours", []))} AS colours,
        {_json_text(summary.get("detected_labels", []))} AS detected_labels,
        {_json_text(summary.get("pattern_summary", {}))} AS pattern_summary,
        {_json_text(title_block)} AS title_block,
        {_json_text(summary.get("document_analysis", {}).get("bom_rows", []))} AS bom_rows,
        {_json_text(summary.get("document_analysis", {}).get("dimensions", {}))} AS dimensions,
        {_json_text(summary.get("document_analysis", {}).get("feature_cues", {}))} AS feature_cues,
        {_json_text(summary.get("document_analysis", {}))} AS document_analysis,
        {_json_text(summary.get("manufacturing_writeup", {}))} AS manufacturing_writeup,
        {_json_text(summary.get("estimate_summary", {}))} AS estimate_summary,
        {_json_text(summary.get("manufacturing_writeup", {}).get("validation", {}))} AS validation,
        {_json_text(summary.get("pdf_metadata", {}))} AS pdf_metadata
) AS source
ON target.run_uuid = source.run_uuid
WHEN MATCHED THEN
    UPDATE SET
        source_file_name = source.source_file_name,
        drawing_numbers = source.drawing_numbers,
        revisions = source.revisions,
        dates = source.dates,
        materials = source.materials,
        surface_finishes = source.surface_finishes,
        colours = source.colours,
        detected_labels = source.detected_labels,
        pattern_summary = source.pattern_summary,
        title_block = source.title_block,
        bom_rows = source.bom_rows,
        dimensions = source.dimensions,
        feature_cues = source.feature_cues,
        document_analysis = source.document_analysis,
        manufacturing_writeup = source.manufacturing_writeup,
        estimate_summary = source.estimate_summary,
        validation = source.validation,
        pdf_metadata = source.pdf_metadata
WHEN NOT MATCHED THEN
    INSERT (
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
    )
    VALUES (
        source.run_uuid,
        source.source_file_name,
        source.drawing_numbers,
        source.revisions,
        source.dates,
        source.materials,
        source.surface_finishes,
        source.colours,
        source.detected_labels,
        source.pattern_summary,
        source.title_block,
        source.bom_rows,
        source.dimensions,
        source.feature_cues,
        source.document_analysis,
        source.manufacturing_writeup,
        source.estimate_summary,
        source.validation,
        source.pdf_metadata
    );""",
    ]

    for page in summary.get("pages", []):
        statements.append(_page_merge_sql(run_uuid, page))

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        statements.append(_part_merge_sql(run_uuid, part))

    statements.append("COMMIT TRANSACTION;")
    return "\n\n".join(statements) + "\n"


def write_sqlserver_insert_sql(summary: Dict[str, Any], sql_path: Path) -> Path:
    sql_path.write_text(generate_sqlserver_insert_sql(summary), encoding="utf-8")
    return sql_path


def export_json_files_to_sqlserver_sql(json_paths: Iterable[Path], output_sql_path: Path) -> Path:
    statements: List[str] = [
        "-- Generated from scan JSON files.",
        "-- Assumes the SQL Server schema in sql/sqlserver_scan_store.sql has already been run.",
    ]
    for json_path in json_paths:
        with json_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
        statements.append(generate_sqlserver_insert_sql(summary, source_json_path=json_path))
    output_sql_path.write_text("\n".join(statements), encoding="utf-8")
    return output_sql_path


# Backward-compatible wrappers for earlier imports.
generate_postgres_insert_sql = generate_sqlserver_insert_sql
write_postgres_insert_sql = write_sqlserver_insert_sql
export_json_files_to_postgres_sql = export_json_files_to_sqlserver_sql
