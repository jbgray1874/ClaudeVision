/* drawingscanstore.v1 - SQL Server schema */
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;

IF OBJECT_ID('dbo.drawing_part','U') IS NOT NULL DROP TABLE dbo.drawing_part;
IF OBJECT_ID('dbo.drawing_page','U') IS NOT NULL DROP TABLE dbo.drawing_page;
IF OBJECT_ID('dbo.drawing_document','U') IS NOT NULL DROP TABLE dbo.drawing_document;
IF OBJECT_ID('dbo.drawing_scan_run','U') IS NOT NULL DROP TABLE dbo.drawing_scan_run;
GO

CREATE TABLE dbo.drawing_scan_run (
    scan_run_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    run_uuid UNIQUEIDENTIFIER NOT NULL,
    source_file_stem NVARCHAR(500) NULL,
    source_file_version INT NULL,
    source_file_version_label NVARCHAR(50) NULL,
    source_file_versioned_name NVARCHAR(500) NULL,
    database_schema_version NVARCHAR(100) NULL,
    source_file NVARCHAR(500) NULL,
    full_path NVARCHAR(1000) NULL,
    scanned_at DATETIME2(0) NULL,
    page_count INT NULL,
    pdf_title NVARCHAR(500) NULL,
    pdf_author NVARCHAR(255) NULL,
    pdf_creator NVARCHAR(255) NULL,
    pdf_producer NVARCHAR(255) NULL,
    pdf_creation_date NVARCHAR(50) NULL,
    pdf_mod_date NVARCHAR(50) NULL,
    raw_json NVARCHAR(MAX) NOT NULL,
    loaded_at DATETIME2(0) NOT NULL CONSTRAINT DF_drawing_scan_run_loaded_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_drawing_scan_run_run_uuid UNIQUE (run_uuid)
);
GO

CREATE TABLE dbo.drawing_document (
    document_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scan_run_id BIGINT NOT NULL,
    drawing_number NVARCHAR(100) NULL,
    revision NVARCHAR(50) NULL,
    material NVARCHAR(255) NULL,
    normalized_material NVARCHAR(255) NULL,
    finish NVARCHAR(255) NULL,
    normalized_finish NVARCHAR(255) NULL,
    colour NVARCHAR(255) NULL,
    quantity DECIMAL(18,4) NULL,
    thickness_mm DECIMAL(18,4) NULL,
    normalized_thickness_mm DECIMAL(18,4) NULL,
    overall_length_mm DECIMAL(18,4) NULL,
    overall_width_mm DECIMAL(18,4) NULL,
    titleblock_confidence DECIMAL(9,4) NULL,
    dimensions_confidence DECIMAL(9,4) NULL,
    processnotes_confidence DECIMAL(9,4) NULL,
    overall_confidence DECIMAL(9,4) NULL,
    document_total_estimated_cost_gbp DECIMAL(18,4) NULL,
    raw_document_analysis_json NVARCHAR(MAX) NULL,
    raw_estimate_summary_json NVARCHAR(MAX) NULL,
    raw_manual_review_json NVARCHAR(MAX) NULL,
    CONSTRAINT FK_drawing_document_scan_run FOREIGN KEY (scan_run_id) REFERENCES dbo.drawing_scan_run(scan_run_id)
);
GO

CREATE TABLE dbo.drawing_page (
    page_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scan_run_id BIGINT NOT NULL,
    page_number INT NOT NULL,
    primary_role NVARCHAR(50) NULL,
    page_role_hint NVARCHAR(50) NULL,
    word_count INT NULL,
    page_width_points DECIMAL(18,4) NULL,
    page_height_points DECIMAL(18,4) NULL,
    drawing_number NVARCHAR(100) NULL,
    revision NVARCHAR(50) NULL,
    material NVARCHAR(255) NULL,
    normalized_material NVARCHAR(255) NULL,
    finish NVARCHAR(255) NULL,
    normalized_finish NVARCHAR(255) NULL,
    colour NVARCHAR(255) NULL,
    quantity DECIMAL(18,4) NULL,
    thickness_mm DECIMAL(18,4) NULL,
    normalized_thickness_mm DECIMAL(18,4) NULL,
    overall_length_mm DECIMAL(18,4) NULL,
    overall_width_mm DECIMAL(18,4) NULL,
    titleblock_confidence DECIMAL(9,4) NULL,
    dimensions_confidence DECIMAL(9,4) NULL,
    processnotes_confidence DECIMAL(9,4) NULL,
    overall_confidence DECIMAL(9,4) NULL,
    pdfplumber_text NVARCHAR(MAX) NULL,
    pypdf_text NVARCHAR(MAX) NULL,
    normalized_text NVARCHAR(MAX) NULL,
    text_preview NVARCHAR(MAX) NULL,
    raw_page_json NVARCHAR(MAX) NOT NULL,
    CONSTRAINT FK_drawing_page_scan_run FOREIGN KEY (scan_run_id) REFERENCES dbo.drawing_scan_run(scan_run_id),
    CONSTRAINT UQ_drawing_page UNIQUE (scan_run_id, page_number)
);
GO

CREATE TABLE dbo.drawing_part (
    part_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scan_run_id BIGINT NOT NULL,
    part_number NVARCHAR(100) NOT NULL,
    item_number NVARCHAR(50) NULL,
    description NVARCHAR(1000) NULL,
    quantity DECIMAL(18,4) NULL,
    page_refs NVARCHAR(200) NULL,
    page_roles NVARCHAR(200) NULL,
    drawing_numbers NVARCHAR(500) NULL,
    revisions NVARCHAR(200) NULL,
    materials NVARCHAR(500) NULL,
    normalized_material NVARCHAR(255) NULL,
    surface_finishes NVARCHAR(500) NULL,
    normalized_finish NVARCHAR(255) NULL,
    colours NVARCHAR(500) NULL,
    thicknesses_mm NVARCHAR(200) NULL,
    normalized_thickness_mm DECIMAL(18,4) NULL,
    overall_length_mm DECIMAL(18,4) NULL,
    overall_width_mm DECIMAL(18,4) NULL,
    process_notes NVARCHAR(MAX) NULL,
    process_note_types NVARCHAR(200) NULL,
    textual_operations NVARCHAR(500) NULL,
    routing_confidence DECIMAL(9,4) NULL,
    review_required BIT NULL,
    geometry_reliability DECIMAL(9,4) NULL,
    estimated_cut_length_mm DECIMAL(18,4) NULL,
    estimated_hole_count INT NULL,
    estimated_slotlike_features INT NULL,
    estimated_bendline_count INT NULL,
    estimated_pierce_count INT NULL,
    unit_total_cost_gbp DECIMAL(18,4) NULL,
    extended_total_cost_gbp DECIMAL(18,4) NULL,
    raw_part_json NVARCHAR(MAX) NOT NULL,
    CONSTRAINT FK_drawing_part_scan_run FOREIGN KEY (scan_run_id) REFERENCES dbo.drawing_scan_run(scan_run_id),
    CONSTRAINT UQ_drawing_part UNIQUE (scan_run_id, part_number)
);
GO

CREATE INDEX IX_drawing_page_scan_run ON dbo.drawing_page(scan_run_id, page_number);
CREATE INDEX IX_drawing_part_scan_run ON dbo.drawing_part(scan_run_id, part_number);
CREATE INDEX IX_drawing_document_scan_run ON dbo.drawing_document(scan_run_id);
GO