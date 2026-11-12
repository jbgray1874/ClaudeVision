-- Read-only. Rebate report (REP-22, SCRUM-275): how the invoiced-sales view is built, and five of
-- its rows, so rebate_rolling.sql can read it. Copy both grids with headers into one file,
-- rebate_source_check.txt.

-- 1. the view's definition (one cell - copy it whole)
SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.UDEF_INVOICED_SALES')) AS view_definition;

-- 2. five rows, every column
SELECT TOP 5 * FROM dbo.UDEF_INVOICED_SALES;
