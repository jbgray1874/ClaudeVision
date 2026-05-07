-- =============================================================================
-- Drawing scan tables + views for SQL Server (SDILive)
-- Matches src/sql_export.py MERGE output (--export-json-to-sql / --export-json-dir-to-sql).
-- All objects under dbo.
--
-- First-time: run this script as-is (idempotent: creates only if missing).
--
-- If you already created WRONG tables (e.g. Postgres-shaped or missing columns),
-- backup any data you need, then run: drawing_scan_store_sqlserver_rebuild.sql
--
-- Index key limits: clustered PK <= 900 bytes; nonclustered <= 1700 bytes (Unicode
-- NVARCHAR counts 2 bytes/char). Wide NVARCHAR columns in keys cause insert failures.
-- source_file_stem is indexed — kept at 255 (typical file stem). part_number is in
-- the clustered PK — kept at 400 chars; full detail remains in part_json (MAX).
-- =============================================================================

-- =============================================
-- DRAWING_SCAN_RUN
-- =============================================
IF OBJECT_ID(N'dbo.drawing_scan_run', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.drawing_scan_run (
        run_uuid UNIQUEIDENTIFIER NOT NULL
            CONSTRAINT PK_drawing_scan_run PRIMARY KEY,
        source_file_name NVARCHAR(4000) NOT NULL,
        source_file_stem NVARCHAR(255) NOT NULL,
        source_file_version INT NOT NULL,
        source_file_version_label NVARCHAR(50) NOT NULL,
        source_file_versioned_name NVARCHAR(4000) NOT NULL,
        source_pdf_path NVARCHAR(4000) NULL,
        scanned_at DATETIME2(3) NULL,
        page_count INT NULL,
        validation_status NVARCHAR(100) NULL,
        latest_json_path NVARCHAR(4000) NULL,
        archive_json_path NVARCHAR(4000) NULL,
        raw_summary_json NVARCHAR(MAX) NOT NULL,
        raw_full_json NVARCHAR(MAX) NOT NULL
    );
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes i
    INNER JOIN sys.tables t ON i.object_id = t.object_id
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE i.name = N'idx_drawing_scan_run_source_file'
      AND s.name = N'dbo'
      AND t.name = N'drawing_scan_run'
)
BEGIN
    CREATE INDEX idx_drawing_scan_run_source_file
        ON dbo.drawing_scan_run (source_file_stem, source_file_version);
END
GO

-- =============================================
-- DRAWING_DOCUMENT  (flattened header fields + raw JSON — matches sql_export.py)
-- =============================================
IF OBJECT_ID(N'dbo.drawing_document', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.drawing_document (
        run_uuid UNIQUEIDENTIFIER NOT NULL
            CONSTRAINT PK_drawing_document PRIMARY KEY
            REFERENCES dbo.drawing_scan_run (run_uuid) ON DELETE CASCADE,
        drawing_number NVARCHAR(4000) NULL,
        revision NVARCHAR(4000) NULL,
        material NVARCHAR(4000) NULL,
        normalized_material NVARCHAR(4000) NULL,
        finish NVARCHAR(4000) NULL,
        normalized_finish NVARCHAR(4000) NULL,
        colour NVARCHAR(4000) NULL,
        quantity DECIMAL(18, 4) NULL,
        thickness_mm DECIMAL(18, 4) NULL,
        normalized_thickness_mm DECIMAL(18, 4) NULL,
        overall_length_mm DECIMAL(18, 4) NULL,
        overall_width_mm DECIMAL(18, 4) NULL,
        titleblock_confidence DECIMAL(18, 4) NULL,
        dimensions_confidence DECIMAL(18, 4) NULL,
        processnotes_confidence DECIMAL(18, 4) NULL,
        overall_confidence DECIMAL(18, 4) NULL,
        document_total_estimated_cost_gbp DECIMAL(18, 4) NULL,
        raw_document_analysis_json NVARCHAR(MAX) NULL,
        raw_estimate_summary_json NVARCHAR(MAX) NULL,
        raw_manual_review_json NVARCHAR(MAX) NULL,
        raw_document_json NVARCHAR(MAX) NULL
    );
END
GO

-- =============================================
-- DRAWING_PAGE  (includes raw_page_json for MERGE)
-- =============================================
IF OBJECT_ID(N'dbo.drawing_page', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.drawing_page (
        run_uuid UNIQUEIDENTIFIER NOT NULL
            REFERENCES dbo.drawing_scan_run (run_uuid) ON DELETE CASCADE,
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
        raw_page_json NVARCHAR(MAX) NULL,
        CONSTRAINT PK_drawing_page PRIMARY KEY (run_uuid, page_number)
    );
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes i
    INNER JOIN sys.tables t ON i.object_id = t.object_id
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE i.name = N'idx_drawing_page_role'
      AND s.name = N'dbo'
      AND t.name = N'drawing_page'
)
BEGIN
    CREATE INDEX idx_drawing_page_role ON dbo.drawing_page (page_role);
END
GO

-- =============================================
-- DRAWING_PART  (part_json + raw_part_json for MERGE)
-- =============================================
IF OBJECT_ID(N'dbo.drawing_part', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.drawing_part (
        run_uuid UNIQUEIDENTIFIER NOT NULL
            REFERENCES dbo.drawing_scan_run (run_uuid) ON DELETE CASCADE,
        part_number NVARCHAR(400) NOT NULL,
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
        raw_part_json NVARCHAR(MAX) NOT NULL,
        CONSTRAINT PK_drawing_part PRIMARY KEY (run_uuid, part_number)
    );
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes i
    INNER JOIN sys.tables t ON i.object_id = t.object_id
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE i.name = N'idx_drawing_part_part_number'
      AND s.name = N'dbo'
      AND t.name = N'drawing_part'
)
BEGIN
    CREATE INDEX idx_drawing_part_part_number ON dbo.drawing_part (part_number);
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes i
    INNER JOIN sys.tables t ON i.object_id = t.object_id
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE i.name = N'idx_drawing_part_run_uuid'
      AND s.name = N'dbo'
      AND t.name = N'drawing_part'
)
BEGIN
    CREATE INDEX idx_drawing_part_run_uuid ON dbo.drawing_part (run_uuid);
END
GO

-- =============================================
-- VIEWS
-- =============================================
CREATE OR ALTER VIEW dbo.v_drawing_latest_run AS
WITH Ranked AS (
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
FROM Ranked
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
JOIN dbo.v_drawing_latest_run r ON r.run_uuid = p.run_uuid;
GO
