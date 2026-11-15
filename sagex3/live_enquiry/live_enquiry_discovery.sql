-- live_enquiry_discovery.sql - READ ONLY (SELECTs only; nothing is created, changed or deleted).
-- Purpose: find where Access SupplyChain (SDILive) holds enquiries / quotes / estimates / prospects,
-- so the Live Enquiry process can be mapped onto Sage X3 opportunities (OPP-00..06, Jira SCRUM-208).
-- SSMS: Query > Results to > Results to Text (tab delimited), run, save as live_enquiry_discovery.rpt
USE SDILive;
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- 1. Tables and views whose NAME suggests enquiries, quotes, estimates, prospects, opportunities, projects, CRM
SELECT 'OBJ' AS grid, s.name AS sch, o.name AS object_name, o.type_desc,
       (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)) AS row_count,
       o.modify_date
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V')
  AND (o.name LIKE '%ENQ%' OR o.name LIKE '%QUOT%' OR o.name LIKE '%QTE%' OR o.name LIKE '%EST%'
       OR o.name LIKE '%PROSP%' OR o.name LIKE '%OPP%' OR o.name LIKE '%PROJ%' OR o.name LIKE '%CRM%'
       OR o.name LIKE '%LEAD%' OR o.name LIKE '%BRIEF%' OR o.name LIKE '%TENDER%' OR o.name LIKE '%PIPE%')
ORDER BY row_count DESC;

-- 2. Columns anywhere whose NAME suggests the same (finds enquiry fields held on other tables)
SELECT 'COL' AS grid, s.name AS sch, o.name AS object_name, o.type_desc, c.name AS column_name, t.name AS data_type, c.max_length
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id AND o.type IN ('U', 'V')
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.name LIKE '%ENQ%' OR c.name LIKE '%QUOT%' OR c.name LIKE '%PROSP%' OR c.name LIKE '%OPP%'
   OR c.name LIKE '%ESTIM%' OR c.name LIKE '%PROBAB%' OR c.name LIKE '%WON%' OR c.name LIKE '%LOST%'
   OR c.name LIKE '%BRIEF%' OR c.name LIKE '%LEAD%'
ORDER BY o.name, c.column_id;

-- 3. Five sample rows from each of the 15 largest candidate tables / views from grid 1 (read-only dynamic SELECTs)
DECLARE @sql nvarchar(max) = N'';
SELECT TOP 15 @sql = @sql + N'SELECT ''SAMPLE'' AS grid, ''' + REPLACE(s.name + '.' + o.name, '''', '''''') + N''' AS source, TOP_ROWS.* FROM (SELECT TOP 5 * FROM '
       + QUOTENAME(s.name) + N'.' + QUOTENAME(o.name) + N') AS TOP_ROWS;' + CHAR(10)
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V')
  AND (o.name LIKE '%ENQ%' OR o.name LIKE '%QUOT%' OR o.name LIKE '%QTE%' OR o.name LIKE '%PROSP%'
       OR o.name LIKE '%OPP%' OR o.name LIKE '%CRM%' OR o.name LIKE '%LEAD%' OR o.name LIKE '%BRIEF%' OR o.name LIKE '%TENDER%')
ORDER BY (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)) DESC;
IF @sql <> N'' EXEC sys.sp_executesql @sql;
