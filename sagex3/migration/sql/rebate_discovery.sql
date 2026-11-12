-- Read-only. Rebate rolling report (Morrisons goalposts): find where Access keeps what the report reads.
-- Results to grid; copy each grid with headers into one file, rebate_discovery.txt.

-- 1. anything already named "rebate" in SDILive (columns, views, procedures)
SELECT 'column' AS kind, TABLE_NAME AS obj, COLUMN_NAME AS detail
FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME LIKE '%REBATE%'
UNION ALL
SELECT o.type_desc, o.name, '' FROM sys.sql_modules m JOIN sys.objects o ON o.object_id = m.object_id
WHERE m.definition LIKE '%rebate%';

-- 2. the order lines behind the report: every column, for the report's customers and part codes
SELECT TOP 60 c.*
FROM dbo.ASC_COR_TBL c
WHERE c.COR_PART_ONLY LIKE '%10932-00-GA%' OR c.COR_PART_ONLY LIKE 'HHA-INSTALL%'
   OR c.COR_PART_ONLY LIKE 'LRS01-%' OR c.COR_PART_ONLY LIKE 'WMM01-GOALPOST%'
ORDER BY c.COR_ORDER_DATE DESC;
