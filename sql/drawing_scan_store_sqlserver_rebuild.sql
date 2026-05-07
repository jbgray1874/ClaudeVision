-- =============================================================================
-- DESTRUCTIVE: drops dbo drawing scan objects (wrong layout / migration).
-- Backup first. Default schema dbo assumed.
--
-- After this script succeeds, run in the same database:
--   drawing_scan_store_sqlserver.sql
-- (creates tables/views; all IF OBJECT_ID IS NULL branches will fire.)
-- =============================================================================

IF OBJECT_ID(N'dbo.v_drawing_part_latest', N'V') IS NOT NULL
    DROP VIEW dbo.v_drawing_part_latest;
GO

IF OBJECT_ID(N'dbo.v_drawing_latest_run', N'V') IS NOT NULL
    DROP VIEW dbo.v_drawing_latest_run;
GO

IF OBJECT_ID(N'dbo.drawing_part', N'U') IS NOT NULL
    DROP TABLE dbo.drawing_part;
GO

IF OBJECT_ID(N'dbo.drawing_page', N'U') IS NOT NULL
    DROP TABLE dbo.drawing_page;
GO

IF OBJECT_ID(N'dbo.drawing_document', N'U') IS NOT NULL
    DROP TABLE dbo.drawing_document;
GO

IF OBJECT_ID(N'dbo.drawing_scan_run', N'U') IS NOT NULL
    DROP TABLE dbo.drawing_scan_run;
GO
