CREATE TABLE IF NOT EXISTS drawing_scan_run (
    run_uuid UUID PRIMARY KEY,
    source_file_name TEXT NOT NULL,
    source_file_stem TEXT NOT NULL,
    source_file_version INTEGER NOT NULL,
    source_file_version_label TEXT NOT NULL,
    source_file_versioned_name TEXT NOT NULL,
    source_pdf_path TEXT,
    scanned_at TIMESTAMP,
    page_count INTEGER,
    validation_status TEXT,
    latest_json_path TEXT,
    archive_json_path TEXT,
    raw_summary_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drawing_scan_run_source_file
    ON drawing_scan_run (source_file_stem, source_file_version);

CREATE TABLE IF NOT EXISTS drawing_document (
    run_uuid UUID PRIMARY KEY REFERENCES drawing_scan_run(run_uuid) ON DELETE CASCADE,
    source_file_name TEXT NOT NULL,
    drawing_numbers JSONB,
    revisions JSONB,
    dates JSONB,
    materials JSONB,
    surface_finishes JSONB,
    colours JSONB,
    detected_labels JSONB,
    pattern_summary JSONB,
    title_block JSONB,
    bom_rows JSONB,
    dimensions JSONB,
    feature_cues JSONB,
    document_analysis JSONB,
    manufacturing_writeup JSONB,
    estimate_summary JSONB,
    validation JSONB,
    pdf_metadata JSONB
);

CREATE TABLE IF NOT EXISTS drawing_page (
    run_uuid UUID NOT NULL REFERENCES drawing_scan_run(run_uuid) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_role TEXT,
    word_count INTEGER,
    page_width NUMERIC(18, 4),
    page_height NUMERIC(18, 4),
    labels_found JSONB,
    pattern_summary JSONB,
    title_block_calibration JSONB,
    region_text JSONB,
    page_analysis JSONB,
    geometry_summary JSONB,
    text_preview TEXT,
    PRIMARY KEY (run_uuid, page_number)
);

CREATE INDEX IF NOT EXISTS idx_drawing_page_role
    ON drawing_page (page_role);

CREATE TABLE IF NOT EXISTS drawing_part (
    run_uuid UUID NOT NULL REFERENCES drawing_scan_run(run_uuid) ON DELETE CASCADE,
    part_number TEXT NOT NULL,
    item_number TEXT,
    description TEXT,
    quantity INTEGER,
    page_roles JSONB,
    pages JSONB,
    materials JSONB,
    surface_finishes JSONB,
    colours JSONB,
    revisions JSONB,
    drawing_numbers JSONB,
    thicknesses_mm JSONB,
    dimensions_mm JSONB,
    angles_deg JSONB,
    hole_sizes_mm JSONB,
    slot_sizes_mm JSONB,
    process_notes JSONB,
    operations JSONB,
    manufacturing_features JSONB,
    manufacturing_interpretation JSONB,
    geometry_rollup JSONB,
    part_json JSONB NOT NULL,
    PRIMARY KEY (run_uuid, part_number)
);

CREATE INDEX IF NOT EXISTS idx_drawing_part_part_number
    ON drawing_part (part_number);

CREATE INDEX IF NOT EXISTS idx_drawing_part_run_uuid
    ON drawing_part (run_uuid);

CREATE OR REPLACE VIEW v_drawing_latest_run AS
SELECT DISTINCT ON (source_file_stem)
    run_uuid,
    source_file_name,
    source_file_stem,
    source_file_version,
    source_file_version_label,
    source_file_versioned_name,
    scanned_at,
    validation_status,
    page_count
FROM drawing_scan_run
ORDER BY source_file_stem, source_file_version DESC, scanned_at DESC;

CREATE OR REPLACE VIEW v_drawing_part_latest AS
SELECT
    r.source_file_name,
    r.source_file_stem,
    r.source_file_version,
    r.source_file_version_label,
    p.part_number,
    p.description,
    p.quantity,
    p.materials,
    p.surface_finishes,
    p.thicknesses_mm,
    p.operations,
    p.manufacturing_features
FROM drawing_part p
JOIN v_drawing_latest_run r
    ON r.run_uuid = p.run_uuid;
