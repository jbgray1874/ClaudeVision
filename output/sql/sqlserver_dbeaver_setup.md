# SQL Server DBeaver Setup

Use this guide when loading drawing scan data into a SQL Server database from DBeaver.

## Files to use

- Schema file:
  - `C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\sql\sqlserver_scan_store.sql`
- SQL export generator code:
  - `C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\sql_export.py`
  - `C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\main.py`
- Generated batch insert file:
  - `C:\ClaudeVision\output\sql\drawing_scan_batch_export.sql`

## First refresh the SQL export file

Copy the latest SQL export code into `C:\ClaudeVision\src`:

```powershell
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\sql_export.py" "C:\ClaudeVision\src\sql_export.py" -Force
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\main.py" "C:\ClaudeVision\src\main.py" -Force
```

Regenerate the SQL Server batch export from the latest JSON files:

```powershell
python .\src\main.py --export-json-dir-to-sql "C:\ClaudeVision\output\json"
```

That recreates:

- `C:\ClaudeVision\output\sql\drawing_scan_batch_export.sql`

## DBeaver notes

- Connect to the SQL Server database you want to use.
- In this project the target database is usually `SDILive`.
- In DBeaver, run the setup in separate chunks.
- Do not rely on `GO` batch separators in this editor mode.
- Run tables first, then indexes, then views, then the batch insert script.

Check the current database first:

```sql
SELECT DB_NAME() AS current_database;
```

If needed:

```sql
USE SDILive;
```

## Clean install sequence

### 1. Drop existing objects

Run this first:

```sql
USE SDILive;

IF OBJECT_ID(N'dbo.v_drawing_part_latest', N'V') IS NOT NULL DROP VIEW dbo.v_drawing_part_latest;
IF OBJECT_ID(N'dbo.v_drawing_latest_run', N'V') IS NOT NULL DROP VIEW dbo.v_drawing_latest_run;

IF OBJECT_ID(N'dbo.drawing_page', N'U') IS NOT NULL DROP TABLE dbo.drawing_page;
IF OBJECT_ID(N'dbo.drawing_part', N'U') IS NOT NULL DROP TABLE dbo.drawing_part;
IF OBJECT_ID(N'dbo.drawing_document', N'U') IS NOT NULL DROP TABLE dbo.drawing_document;
IF OBJECT_ID(N'dbo.drawing_scan_run', N'U') IS NOT NULL DROP TABLE dbo.drawing_scan_run;
```

### 2. Create tables

Run this next:

```sql
CREATE TABLE dbo.drawing_scan_run (
    run_uuid UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    source_file_name NVARCHAR(512) NOT NULL,
    source_file_stem NVARCHAR(512) NOT NULL,
    source_file_version INT NOT NULL,
    source_file_version_label NVARCHAR(50) NOT NULL,
    source_file_versioned_name NVARCHAR(512) NOT NULL,
    source_pdf_path NVARCHAR(2000) NULL,
    scanned_at DATETIME2 NULL,
    page_count INT NULL,
    validation_status NVARCHAR(100) NULL,
    latest_json_path NVARCHAR(2000) NULL,
    archive_json_path NVARCHAR(2000) NULL,
    raw_summary_json NVARCHAR(MAX) NOT NULL
);

CREATE TABLE dbo.drawing_document (
    run_uuid UNIQUEIDENTIFIER NOT NULL PRIMARY KEY
        REFERENCES dbo.drawing_scan_run(run_uuid) ON DELETE CASCADE,
    source_file_name NVARCHAR(512) NOT NULL,
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

CREATE TABLE dbo.drawing_part (
    run_uuid UNIQUEIDENTIFIER NOT NULL
        REFERENCES dbo.drawing_scan_run(run_uuid) ON DELETE CASCADE,
    part_number NVARCHAR(255) NOT NULL,
    item_number NVARCHAR(255) NULL,
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
```

### 3. Create indexes

Run this after the tables:

```sql
CREATE INDEX idx_drawing_scan_run_source_file
    ON dbo.drawing_scan_run (source_file_stem, source_file_version);

CREATE INDEX idx_drawing_page_role
    ON dbo.drawing_page (page_role);

CREATE INDEX idx_drawing_part_part_number
    ON dbo.drawing_part (part_number);

CREATE INDEX idx_drawing_part_run_uuid
    ON dbo.drawing_part (run_uuid);
```

### 4. Create views

Run each view separately.

First:

```sql
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
```

Then:

```sql
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
```

## Sanity checks

After setup:

```sql
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME IN (
    'drawing_scan_run',
    'drawing_document',
    'drawing_page',
    'drawing_part'
  );

SELECT name
FROM sys.views
WHERE name IN ('v_drawing_latest_run', 'v_drawing_part_latest');
```

## Load the scan data

After the schema and views exist, run this file in DBeaver:

- `C:\ClaudeVision\output\sql\drawing_scan_batch_export.sql`

## Reload cycle for future test databases

1. Run or rerun the PDF scans to refresh JSON files
2. Regenerate the SQL batch file:

```powershell
python .\src\main.py --export-json-dir-to-sql "C:\ClaudeVision\output\json"
```

3. In DBeaver:
   - run the clean install sequence if this is a fresh database
   - or just rerun `drawing_scan_batch_export.sql` if the schema already exists and you only want to load new versions

## Suggested first import checks

```sql
SELECT COUNT(*) AS run_count
FROM dbo.drawing_scan_run;

SELECT COUNT(*) AS document_count
FROM dbo.drawing_document;

SELECT COUNT(*) AS page_count
FROM dbo.drawing_page;

SELECT COUNT(*) AS part_count
FROM dbo.drawing_part;
```

```sql
SELECT TOP 20 *
FROM dbo.v_drawing_latest_run
ORDER BY source_file_stem;
```

```sql
SELECT TOP 50 *
FROM dbo.v_drawing_part_latest
ORDER BY source_file_stem, part_number;
```
