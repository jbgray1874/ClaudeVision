-- works_orders_discovery.sql  -  READ ONLY, changes nothing
--
-- For Ethan's new YA004MFG template (open works orders). It needs, per works order:
-- product, start date, end date, quantity still to make, and order number.
--
-- We have only ever used two columns of the works order table (WOR_ITEM_ONLY, the product,
-- and WOR_DATE_SCHED), so this finds the rest before the extract is written. Grid 4 pulls
-- the Access works orders for the products in Ethan's example rows, so his example can be
-- matched field by field to Access.
-- Five grids. Paste them all back.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. Every column on the works order table =====
SELECT c.column_id, c.name AS [column], ty.name AS [type], c.max_length
FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dbo.ASC_WOR_TBL')
ORDER BY c.column_id;

-- ===== 2. Other tables that look like works order tables =====
SELECT t.name AS [table],
       (SELECT SUM(p.rows) FROM sys.partitions p
         WHERE p.object_id = t.object_id AND p.index_id IN (0, 1)) AS [rows]
FROM sys.tables t
WHERE t.name LIKE '%WOR%' OR t.name LIKE '%WORKS%' OR t.name LIKE '%MFG%' OR t.name LIKE '%JOB%'
ORDER BY 2 DESC;

-- ===== 3. The size of it, and how recent =====
SELECT COUNT(*) AS works_order_rows,
       COUNT(DISTINCT LTRIM(RTRIM(WOR_ITEM_ONLY))) AS products,
       CONVERT(varchar(10), MIN(WOR_DATE_SCHED), 23) AS oldest_scheduled,
       CONVERT(varchar(10), MAX(WOR_DATE_SCHED), 23) AS newest_scheduled,
       SUM(CASE WHEN WOR_DATE_SCHED >= DATEADD(month, -6, GETDATE()) THEN 1 ELSE 0 END) AS last_6_months
FROM dbo.ASC_WOR_TBL;

-- ===== 4. The works orders behind Ethan's example rows =====
-- His examples: TES-8192 534, TES-11106-01-01 117, 7241-GA-002OS 1, BOT-12422-02-GA 251,
-- MS-0350875 3, SRS-12422-16 348, SRS-12422-23 58, SRS-12422-42 203, MS-0347061 50,
-- SRS-12422-14-GA2 12, SRS-12422-09 48, SRS-12422-11 6. Matching these quantities and dates
-- to Access tells us which columns he used.
SELECT TOP 200 *
FROM dbo.ASC_WOR_TBL
WHERE LTRIM(RTRIM(WOR_ITEM_ONLY)) IN ('TES-8192', 'TES-11106-01-01', '7241-GA-002OS', 'BOT-12422-02-GA',
        'MS-0350875', 'SRS-12422-16', 'SRS-12422-23', 'SRS-12422-42', 'MS-0347061',
        'SRS-12422-14-GA2', 'SRS-12422-09', 'SRS-12422-11')
  AND WOR_DATE_SCHED >= '20260701'
ORDER BY WOR_ITEM_ONLY, WOR_DATE_SCHED;

-- ===== 5. Values of the columns that look like a status, so we can tell open from closed =====
DECLARE @sql nvarchar(max);
SELECT @sql = STUFF((
    SELECT ' UNION ALL SELECT ''' + c.name + ''' AS [column], CAST(' + QUOTENAME(c.name)
         + ' AS nvarchar(40)) COLLATE DATABASE_DEFAULT AS [value], COUNT(*) AS [rows],'
         + ' SUM(CASE WHEN WOR_DATE_SCHED >= DATEADD(month, -6, GETDATE()) THEN 1 ELSE 0 END) AS last_6_months'
         + ' FROM dbo.ASC_WOR_TBL GROUP BY ' + QUOTENAME(c.name)
    FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE c.object_id = OBJECT_ID('dbo.ASC_WOR_TBL')
      AND (c.name LIKE '%STATUS%' OR c.name LIKE '%STAT' OR c.name LIKE '%COMPLETE%'
           OR c.name LIKE '%CLOSED%' OR c.name LIKE '%TYPE%' OR c.name LIKE '%FLAG%')
      AND ty.name IN ('varchar', 'nvarchar', 'char', 'nchar', 'tinyint', 'smallint', 'int', 'bit')
    FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 11, '');
IF @sql IS NOT NULL
BEGIN
    SET @sql = N'SELECT * FROM (' + @sql + N') x WHERE [rows] > 0 ORDER BY [column], [rows] DESC';
    EXEC sp_executesql @sql;
END
GO
