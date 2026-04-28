IF OBJECT_ID(N'dbo.drawing_page', N'U') IS NOT NULL DROP TABLE dbo.drawing_page;
IF OBJECT_ID(N'dbo.drawing_part', N'U') IS NOT NULL DROP TABLE dbo.drawing_part;
IF OBJECT_ID(N'dbo.drawing_document', N'U') IS NOT NULL DROP TABLE dbo.drawing_document;
IF OBJECT_ID(N'dbo.drawing_scan_run', N'U') IS NOT NULL DROP TABLE dbo.drawing_scan_run;
GO

CREATE TABLE dbo.drawing_scan_run (
    run_uuid UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    source_file_name NVARCHAR(4000) NOT NULL,
    source_file_stem NVARCHAR(4000) NOT NULL,
    source_file_version INT NOT NULL,
    source_file_version_label NVARCHAR(50) NOT NULL,
    source_file_versioned_name NVARCHAR(4000) NOT NULL,
    source_pdf_path NVARCHAR(4000) NULL,
    scanned_at DATETIME2 NULL,
    page_count INT NULL,
    validation_status NVARCHAR(100) NULL,
    latest_json_path NVARCHAR(4000) NULL,
    archive_json_path NVARCHAR(4000) NULL,
    raw_summary_json NVARCHAR(MAX) NOT NULL
);
GO

CREATE INDEX idx_drawing_scan_run_source_file
    ON dbo.drawing_scan_run (source_file_stem, source_file_version);
GO

CREATE TABLE dbo.drawing_document (
    run_uuid UNIQUEIDENTIFIER NOT NULL PRIMARY KEY
        REFERENCES dbo.drawing_scan_run(run_uuid) ON DELETE CASCADE,
    source_file_name NVARCHAR(4000) NOT NULL,
    drawing_numbers NVARCHAR(MAX) NULL,
    revisions NVARCHAR(MAX) NULL,
    dates NVARCHAR(MAX) NULL,
    materials NVARCHAR(MAX) NULL,
    surface_finishes NVARCHAR(MAX) NULL,
    colours NVARCHAR(MAX) NULL,
    detected_labels NVARCHAR(MAX) NULL,
    pattern_summary NVARCHAR(MAX) NULL,
    title_block NVARCHAR(MAX) NULL,
    bom_rows NVARCHAR(MAX) NULL,
    dimensions NVARCHAR(MAX) NULL,
    feature_cues NVARCHAR(MAX) NULL,
    document_analysis NVARCHAR(MAX) NULL,
    manufacturing_writeup NVARCHAR(MAX) NULL,
    estimate_summary NVARCHAR(MAX) NULL,
    validation NVARCHAR(MAX) NULL,
    pdf_metadata NVARCHAR(MAX) NULL
);
GO

CREATE TABLE dbo.drawing_page (
    run_uuid UNIQUEIDENTIFIER NOT NULL
        REFERENCES dbo.drawing_scan_run(run_uuid) ON DELETE CASCADE,
    page_number INT NOT NULL,
    page_role NVARCHAR(100) NULL,
    word_count INT NULL,
    page_width DECIMAL(18, 4) NULL,
    page_height DECIMAL(18, 4) NULL,
    labels_found NVARCHAR(MAX) NULL,
    pattern_summary NVARCHAR(MAX) NULL,
    title_block_calibration NVARCHAR(MAX) NULL,
    region_text NVARCHAR(MAX) NULL,
    page_analysis NVARCHAR(MAX) NULL,
    geometry_summary NVARCHAR(MAX) NULL,
    text_preview NVARCHAR(MAX) NULL,
    CONSTRAINT PK_drawing_page PRIMARY KEY (run_uuid, page_number)
);
GO

CREATE INDEX idx_drawing_page_role
    ON dbo.drawing_page (page_role);
GO

CREATE TABLE dbo.drawing_part (
    run_uuid UNIQUEIDENTIFIER NOT NULL
        REFERENCES dbo.drawing_scan_run(run_uuid) ON DELETE CASCADE,
    part_number NVARCHAR(4000) NOT NULL,
    item_number NVARCHAR(4000) NULL,
    description NVARCHAR(MAX) NULL,
    quantity INT NULL,
    page_roles NVARCHAR(MAX) NULL,
    pages NVARCHAR(MAX) NULL,
    materials NVARCHAR(MAX) NULL,
    surface_finishes NVARCHAR(MAX) NULL,
    colours NVARCHAR(MAX) NULL,
    revisions NVARCHAR(MAX) NULL,
    drawing_numbers NVARCHAR(MAX) NULL,
    thicknesses_mm NVARCHAR(MAX) NULL,
    dimensions_mm NVARCHAR(MAX) NULL,
    angles_deg NVARCHAR(MAX) NULL,
    hole_sizes_mm NVARCHAR(MAX) NULL,
    slot_sizes_mm NVARCHAR(MAX) NULL,
    process_notes NVARCHAR(MAX) NULL,
    operations NVARCHAR(MAX) NULL,
    manufacturing_features NVARCHAR(MAX) NULL,
    manufacturing_interpretation NVARCHAR(MAX) NULL,
    geometry_rollup NVARCHAR(MAX) NULL,
    part_json NVARCHAR(MAX) NOT NULL,
    CONSTRAINT PK_drawing_part PRIMARY KEY (run_uuid, part_number)
);
GO

CREATE INDEX idx_drawing_part_part_number
    ON dbo.drawing_part (part_number);
GO

CREATE INDEX idx_drawing_part_run_uuid
    ON dbo.drawing_part (run_uuid);
GO

CREATE OR ALTER VIEW dbo.v_drawing_latest_run AS
WITH ranked AS (
    SELECT
        run_uuid,
        source_file_name,
        source_file_stem,
        source_file_version,
        source_file_version_label,
        source_file_versioned_name,
        scanned_at,
        validation_status,
        page_count,
        ROW_NUMBER() OVER (
            PARTITION BY source_file_stem
            ORDER BY source_file_version DESC, scanned_at DESC
        ) AS rn
    FROM dbo.drawing_scan_run
)
SELECT
    run_uuid,
    source_file_name,
    source_file_stem,
    source_file_version,
    source_file_version_label,
    source_file_versioned_name,
    scanned_at,
    validation_status,
    page_count
FROM ranked
WHERE rn = 1;
GO

CREATE OR ALTER VIEW dbo.v_drawing_part_latest AS
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
FROM dbo.drawing_part p
JOIN dbo.v_drawing_latest_run r
    ON r.run_uuid = p.run_uuid;
GO
