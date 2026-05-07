/*
  Step 1: Verify UDEF schema and query compatibility in SSMS.
  Run this before production estimate runs.
*/

SET NOCOUNT ON;

PRINT '--- UDEF table metadata ---';
EXEC sp_help 'dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING';

PRINT '--- SUP_TBL metadata ---';
EXEC sp_help 'dbo.SUP_TBL';

PRINT '--- Required UDEF columns check ---';
SELECT c.name AS column_name
FROM sys.columns c
WHERE c.object_id = OBJECT_ID('dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING')
  AND c.name IN ('Part ref', 'Description', 'System cost per', 'Cus code')
ORDER BY c.name;

PRINT '--- Required SUP_TBL column check ---';
SELECT c.name AS column_name
FROM sys.columns c
WHERE c.object_id = OBJECT_ID('dbo.SUP_TBL')
  AND c.name IN ('SUP_CODE', 'SUP_NAME')
ORDER BY c.name;

PRINT '--- Smoke test UDEF lookup query ---';
DECLARE @part_code NVARCHAR(100) = N'11234-01-M01';
DECLARE @desc      NVARCHAR(200) = N'MAIN SECTION FRAME WELDMENT';

SELECT TOP 5
    u.[Part ref] AS part_code,
    u.[Description] AS description,
    u.[System cost per] AS system_cost_per,
    CAST(u.[System cost per] AS DECIMAL(18,4)) AS price,
    u.[Cus code] AS supplier_code,
    s.[SUP_NAME] AS supplier_name,
    GETDATE() AS price_date
FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
LEFT JOIN dbo.SUP_TBL s
    ON s.[SUP_CODE] = u.[Cus code]
WHERE
    UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(@part_code)))
    OR UPPER(u.[Description]) LIKE '%' + UPPER(@desc) + '%'
ORDER BY
    CASE WHEN UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(@part_code))) THEN 0 ELSE 1 END,
    u.[System cost per] DESC;

PRINT 'Verification complete.';
