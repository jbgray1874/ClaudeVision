-- 00_discover.sql  -  READ ONLY, changes nothing. Run once, to build the product extract on facts.
--
-- What the repeatable product extract needs to know, and the repo doesn't have:
--   1  the full text of the migration views that picked the product file (vw_ITM, vw_DQ_ITM,
--      vw_BOMP, vw_ROU ...) - only fragments were ever seen
--   2  the columns of the Access tables behind products, BOMs, routes, costs and stock
--   3  row counts, to size the extract
-- Fast: system tables only, plus three sample rows per table.
--
-- Results To File, tab delimited, ONE file, and send it back. Each grid starts with a label column.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- 1. Every migration view, in full (one row per view)
SELECT 'VIEW' AS grid, o.name AS [object],
       REPLACE(REPLACE(OBJECT_DEFINITION(o.object_id), CHAR(13), ' '), CHAR(10), ' ') AS [definition]
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name = 'migration' AND o.type = 'V'
ORDER BY o.name;

-- 2. The columns of the product-side Access tables, and any table whose name suggests routes,
--    operations, work centres or costs
SELECT 'COLUMN' AS grid, t.name AS [table], c.column_id, c.name AS [column], ty.name AS [type], c.max_length
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id AND s.name = 'dbo'
JOIN sys.columns c ON c.object_id = t.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE t.name IN ('STK_STOCK', 'STK_STOCK_2', 'STK_STOCK_3', 'ASC_PMA_TBL', 'ASC_BOM_TBL', 'ASC_LOT_TBL',
                 'ASC_WOR_TBL', 'ASC_TYP_TBL', 'ASC_JBC_TBL', 'ASC_JBR_TBL', 'ASC_WKK_TBL', 'ASC_PLN_TBL',
                 'ASC_DEF_TBL', 'ASC_PID_TBL', 'ASC_PIR_TBL', 'ASC_PPD_TBL')
   OR t.name LIKE '%ROUT%' OR t.name LIKE '%OPER%' OR t.name LIKE '%WORKC%' OR t.name LIKE '%COST%'
ORDER BY t.name, c.column_id;

-- 3. Row counts for the same tables
SELECT 'ROWS' AS grid, t.name AS [table], SUM(p.rows) AS [rows]
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id AND s.name = 'dbo'
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.name IN ('STK_STOCK', 'STK_STOCK_2', 'STK_STOCK_3', 'ASC_PMA_TBL', 'ASC_BOM_TBL', 'ASC_LOT_TBL',
                 'ASC_WOR_TBL', 'ASC_TYP_TBL', 'ASC_JBC_TBL', 'ASC_JBR_TBL', 'ASC_WKK_TBL', 'ASC_PLN_TBL',
                 'ASC_DEF_TBL', 'ASC_PID_TBL', 'ASC_PIR_TBL', 'ASC_PPD_TBL')
   OR t.name LIKE '%ROUT%' OR t.name LIKE '%OPER%' OR t.name LIKE '%WORKC%' OR t.name LIKE '%COST%'
GROUP BY t.name
ORDER BY t.name;

-- 4. Three sample rows from each core table, to see what the columns hold
SELECT TOP 3 'SAMPLE STK_STOCK' AS grid, * FROM dbo.STK_STOCK WHERE STKCODE = '9758-00-GA' OR STKCODE LIKE 'FIXING4%';
SELECT TOP 3 'SAMPLE ASC_PMA_TBL' AS grid, * FROM dbo.ASC_PMA_TBL;
SELECT TOP 3 'SAMPLE ASC_BOM_TBL' AS grid, * FROM dbo.ASC_BOM_TBL;
GO
