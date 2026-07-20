import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config
from pricing_variance import build_pricing_variance_rows


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


def _first(values: Any) -> Any:
    if isinstance(values, list) and values:
        return values[0]
    return None


def _json_text(value: Any) -> str:
    def _json_default(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, Path):
            return str(obj)
        return str(obj)

    payload = json.dumps(value if value is not None else {}, ensure_ascii=False, default=_json_default)
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


def _document_row(summary: Dict[str, Any]) -> Dict[str, Any]:
    document_analysis = summary.get("document_analysis", {})
    title_block = document_analysis.get("title_block", {})
    primary = document_analysis.get("primary_fields", {})
    estimate_summary = summary.get("estimate_summary", {})
    confidence = document_analysis.get("confidence", {})

    return {
        "drawing_number": primary.get("drawing_number") or _first(title_block.get("drawing_numbers", [])),
        "revision": primary.get("revision") or _first(title_block.get("revisions", [])),
        "material": primary.get("material") or _first(title_block.get("materials", [])),
        "normalized_material": primary.get("normalized_material") or title_block.get("normalized", {}).get("primary_material"),
        "finish": primary.get("finish") or _first(title_block.get("surface_finishes", [])),
        "normalized_finish": primary.get("normalized_finish") or title_block.get("normalized", {}).get("primary_finish"),
        "colour": primary.get("colour") or _first(title_block.get("colours", [])),
        "quantity": primary.get("quantity"),
        "thickness_mm": primary.get("thickness_mm"),
        "normalized_thickness_mm": primary.get("normalized_thickness_mm") or title_block.get("normalized", {}).get("primary_thickness_mm"),
        "overall_length_mm": primary.get("overall_length_mm"),
        "overall_width_mm": primary.get("overall_width_mm"),
        "titleblock_confidence": confidence.get("title_block"),
        "dimensions_confidence": confidence.get("dimensions"),
        "processnotes_confidence": confidence.get("process_notes"),
        "overall_confidence": confidence.get("overall"),
        "document_total_estimated_cost_gbp": estimate_summary.get("document_total_estimated_cost_gbp"),
        "raw_document_analysis_json": document_analysis,
        "raw_estimate_summary_json": estimate_summary,
        "raw_manual_review_json": summary.get("manual_review_items", []),
        "raw_document_json": {
            "document_analysis": document_analysis,
            "manual_review_items": summary.get("manual_review_items", []),
            "estimate_summary": estimate_summary,
            "manufacturing_writeup": summary.get("manufacturing_writeup", {}),
        },
    }


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
        {_sql_text(page.get("text_preview"))} AS text_preview,
        {_json_text(page)} AS raw_page_json
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
        text_preview = source.text_preview,
        raw_page_json = source.raw_page_json
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
        text_preview,
        raw_page_json
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
        source.text_preview,
        source.raw_page_json
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
        {_json_text(part)} AS part_json,
        {_json_text(part)} AS raw_part_json
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
        part_json = source.part_json,
        raw_part_json = source.raw_part_json
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
        part_json,
        raw_part_json
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
        source.part_json,
        source.raw_part_json
    );"""


def _pricing_variance_insert_sql(row: Dict[str, Any]) -> str:
    return f"""INSERT INTO dbo.pricing_variance (
    run_uuid,
    source_file_name,
    part_number,
    comparison_scope,
    metric_name,
    manual_value,
    ai_value,
    abs_variance,
    pct_variance,
    status,
    notes,
    manual_source,
    ai_source
) VALUES (
    CAST({_sql_quote(row.get("run_uuid"))} AS uniqueidentifier),
    {_sql_text(row.get("source_file_name"))},
    {_sql_text(row.get("part_number"))},
    {_sql_text(row.get("comparison_scope"))},
    {_sql_text(row.get("metric_name"))},
    {_sql_numeric(row.get("manual_value"))},
    {_sql_numeric(row.get("ai_value"))},
    {_sql_numeric(row.get("abs_variance"))},
    {_sql_numeric(row.get("pct_variance"))},
    {_sql_text(row.get("status"))},
    {_sql_text(row.get("notes"))},
    {_sql_text(row.get("manual_source"))},
    {_sql_text(row.get("ai_source"))}
);"""


def generate_sqlserver_insert_sql(summary: Dict[str, Any], source_json_path: Optional[Path] = None) -> str:
    metadata = build_run_metadata(summary, source_json_path=source_json_path)
    run_uuid = metadata["run_uuid"]
    document_row = _document_row(summary)

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
        {_json_text(summary)} AS raw_summary_json,
        {_json_text(summary)} AS raw_full_json
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
        raw_summary_json = source.raw_summary_json,
        raw_full_json = source.raw_full_json
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
        raw_summary_json,
        raw_full_json
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
        source.raw_summary_json,
        source.raw_full_json
    );""",
        f"""MERGE INTO dbo.drawing_document AS target
USING (
    SELECT
        CAST({_sql_quote(run_uuid)} AS uniqueidentifier) AS run_uuid,
        {_sql_text(document_row.get("drawing_number"))} AS drawing_number,
        {_sql_text(document_row.get("revision"))} AS revision,
        {_sql_text(document_row.get("material"))} AS material,
        {_sql_text(document_row.get("normalized_material"))} AS normalized_material,
        {_sql_text(document_row.get("finish"))} AS finish,
        {_sql_text(document_row.get("normalized_finish"))} AS normalized_finish,
        {_sql_text(document_row.get("colour"))} AS colour,
        {_sql_numeric(document_row.get("quantity"))} AS quantity,
        {_sql_numeric(document_row.get("thickness_mm"))} AS thickness_mm,
        {_sql_numeric(document_row.get("normalized_thickness_mm"))} AS normalized_thickness_mm,
        {_sql_numeric(document_row.get("overall_length_mm"))} AS overall_length_mm,
        {_sql_numeric(document_row.get("overall_width_mm"))} AS overall_width_mm,
        {_sql_numeric(document_row.get("titleblock_confidence"))} AS titleblock_confidence,
        {_sql_numeric(document_row.get("dimensions_confidence"))} AS dimensions_confidence,
        {_sql_numeric(document_row.get("processnotes_confidence"))} AS processnotes_confidence,
        {_sql_numeric(document_row.get("overall_confidence"))} AS overall_confidence,
        {_sql_numeric(document_row.get("document_total_estimated_cost_gbp"))} AS document_total_estimated_cost_gbp,
        {_json_text(document_row.get("raw_document_analysis_json"))} AS raw_document_analysis_json,
        {_json_text(document_row.get("raw_estimate_summary_json"))} AS raw_estimate_summary_json,
        {_json_text(document_row.get("raw_manual_review_json"))} AS raw_manual_review_json,
        {_json_text(document_row.get("raw_document_json"))} AS raw_document_json
) AS source
ON target.run_uuid = source.run_uuid
WHEN MATCHED THEN
    UPDATE SET
        drawing_number = source.drawing_number,
        revision = source.revision,
        material = source.material,
        normalized_material = source.normalized_material,
        finish = source.finish,
        normalized_finish = source.normalized_finish,
        colour = source.colour,
        quantity = source.quantity,
        thickness_mm = source.thickness_mm,
        normalized_thickness_mm = source.normalized_thickness_mm,
        overall_length_mm = source.overall_length_mm,
        overall_width_mm = source.overall_width_mm,
        titleblock_confidence = source.titleblock_confidence,
        dimensions_confidence = source.dimensions_confidence,
        processnotes_confidence = source.processnotes_confidence,
        overall_confidence = source.overall_confidence,
        document_total_estimated_cost_gbp = source.document_total_estimated_cost_gbp,
        raw_document_analysis_json = source.raw_document_analysis_json,
        raw_estimate_summary_json = source.raw_estimate_summary_json,
        raw_manual_review_json = source.raw_manual_review_json,
        raw_document_json = source.raw_document_json
WHEN NOT MATCHED THEN
    INSERT (
        run_uuid,
        drawing_number,
        revision,
        material,
        normalized_material,
        finish,
        normalized_finish,
        colour,
        quantity,
        thickness_mm,
        normalized_thickness_mm,
        overall_length_mm,
        overall_width_mm,
        titleblock_confidence,
        dimensions_confidence,
        processnotes_confidence,
        overall_confidence,
        document_total_estimated_cost_gbp,
        raw_document_analysis_json,
        raw_estimate_summary_json,
        raw_manual_review_json,
        raw_document_json
    )
    VALUES (
        source.run_uuid,
        source.drawing_number,
        source.revision,
        source.material,
        source.normalized_material,
        source.finish,
        source.normalized_finish,
        source.colour,
        source.quantity,
        source.thickness_mm,
        source.normalized_thickness_mm,
        source.overall_length_mm,
        source.overall_width_mm,
        source.titleblock_confidence,
        source.dimensions_confidence,
        source.processnotes_confidence,
        source.overall_confidence,
        source.document_total_estimated_cost_gbp,
        source.raw_document_analysis_json,
        source.raw_estimate_summary_json,
        source.raw_manual_review_json,
        source.raw_document_json
    );""",
    ]

    for page in summary.get("pages", []):
        statements.append(_page_merge_sql(run_uuid, page))

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        statements.append(_part_merge_sql(run_uuid, part))

    variance_rows = summary.get("pricing_variance_rows")
    if not isinstance(variance_rows, list):
        variance_rows = build_pricing_variance_rows(summary)
        summary["pricing_variance_rows"] = variance_rows
    for row in variance_rows:
        statements.append(_pricing_variance_insert_sql(row))

    statements.append("COMMIT TRANSACTION;")
    return "\n\n".join(statements) + "\n"


def write_sqlserver_insert_sql(summary: Dict[str, Any], sql_path: Path) -> Path:
    sql_path.write_text(generate_sqlserver_insert_sql(summary), encoding="utf-8")
    return sql_path


def export_single_json_file_to_sqlserver_sql(json_path: Path, output_sql_path: Path) -> Path:
    with json_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)
    statements = [
        "-- Generated from a scan JSON file.",
        "-- Assumes the SQL Server schema in sql/sqlserver_scan_store.sql has already been run.",
        generate_sqlserver_insert_sql(summary, source_json_path=json_path),
    ]
    output_sql_path.write_text("\n".join(statements), encoding="utf-8")
    return output_sql_path


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


generate_postgres_insert_sql = generate_sqlserver_insert_sql
write_postgres_insert_sql = write_sqlserver_insert_sql
export_json_files_to_postgres_sql = export_json_files_to_sqlserver_sql
