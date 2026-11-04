-- extract_routes.sql  -  READ ONLY, changes nothing (temporary tables in tempdb only)
--
-- Live route data for ZSDIROU2. The route file so far came from migration.LOAD_ROU, a table made
-- once by a one-off script (31,326 operations), not from live data (rule 1). Access's live route
-- table looks to be ASC_PLN_TBL (64,830 rows). This pulls both, whole, so the kit can build the
-- routes from the live table and check them against LOAD_ROU (work-centre mapping, times):
--   DEF      the definitions of migration.vw_ROU / vw_DQ_ROU, and what LOAD_ROU / DQ_ROU are
--   COLUMN   the columns of every table below, so the rows can be read
--   PLN      every row of dbo.ASC_PLN_TBL           (live routes / operations)
--   LOADROU  every row of migration.LOAD_ROU        (what the old file was built from)
--   ROU      every row of migration.vw_ROU          (the view the old file used)
--   WKC_<table>  every row of each work-centre table, if found (names like %WKC%, %WORKC%, ASC_CEN%)
-- Text has tabs and line breaks replaced by spaces, so every row stays one line.
--
-- Run after nothing else in particular. Results To File, tab delimited, one file, and send it
-- back as extract_routes.txt. Each grid starts with its label. Expect a minute.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'CHECK' AS grid, 'as at' AS item, CONVERT(varchar(19), GETDATE(), 120) AS value;

-- what the route objects are
SELECT 'DEF' AS grid, s.name + '.' + o.name AS object, o.type_desc,
       REPLACE(REPLACE(REPLACE(ISNULL(OBJECT_DEFINITION(o.object_id), ''), CHAR(9), ' '), CHAR(13), ' '), CHAR(10), ' ') AS definition
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE (s.name = 'migration' AND o.name IN ('vw_ROU', 'vw_DQ_ROU', 'LOAD_ROU', 'DQ_ROU'))
   OR (s.name = 'dbo' AND o.name IN ('ASC_PLN_TBL', 'ASC_API_RTE_TBL'));

-- the tables to dump: route tables plus anything that looks like a work-centre table
IF OBJECT_ID('tempdb..#dump') IS NOT NULL DROP TABLE #dump;
CREATE TABLE #dump (label varchar(80), sch sysname, tbl sysname);
INSERT INTO #dump SELECT 'PLN', 'dbo', 'ASC_PLN_TBL' WHERE OBJECT_ID('dbo.ASC_PLN_TBL') IS NOT NULL;
INSERT INTO #dump SELECT 'LOADROU', 'migration', 'LOAD_ROU' WHERE OBJECT_ID('migration.LOAD_ROU') IS NOT NULL;
INSERT INTO #dump SELECT 'ROU', 'migration', 'vw_ROU' WHERE OBJECT_ID('migration.vw_ROU') IS NOT NULL;
INSERT INTO #dump SELECT 'WKC_' + UPPER(t.name), s.name, t.name
FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = 'dbo' AND (t.name LIKE '%WKC%' OR t.name LIKE '%WORKC%' OR t.name LIKE 'ASC[_]CEN%' OR t.name LIKE 'ASC[_]WCE%');

SELECT 'COLUMN' AS grid, d.label, d.sch + '.' + d.tbl AS [table], c.column_id, c.name AS [column], ty.name AS type
FROM #dump d
JOIN sys.columns c ON c.object_id = OBJECT_ID(QUOTENAME(d.sch) + '.' + QUOTENAME(d.tbl))
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
ORDER BY d.label, d.tbl, c.column_id;

-- each table whole, text columns made single-line
DECLARE @label varchar(80), @sch sysname, @tbl sysname, @cols nvarchar(max), @sql nvarchar(max);
DECLARE t CURSOR LOCAL FAST_FORWARD FOR SELECT label, sch, tbl FROM #dump ORDER BY label, tbl;
OPEN t;
FETCH NEXT FROM t INTO @label, @sch, @tbl;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @cols = STUFF((
        SELECT ', ' + CASE WHEN ty.name IN ('char', 'varchar', 'nchar', 'nvarchar', 'text', 'ntext')
                      THEN 'REPLACE(REPLACE(REPLACE(CAST(' + QUOTENAME(c.name) + ' AS nvarchar(max)), CHAR(9), '' ''), CHAR(13), '' ''), CHAR(10), '' '') AS ' + QUOTENAME(c.name)
                      ELSE QUOTENAME(c.name) END
        FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        WHERE c.object_id = OBJECT_ID(QUOTENAME(@sch) + '.' + QUOTENAME(@tbl))
          AND ty.name NOT IN ('image', 'varbinary', 'binary', 'timestamp', 'xml')
        ORDER BY c.column_id
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');
    SET @sql = N'SELECT ''' + @label + N''' AS grid, ' + @cols + N' FROM ' + QUOTENAME(@sch) + N'.' + QUOTENAME(@tbl) + N';';
    EXEC sp_executesql @sql;
    FETCH NEXT FROM t INTO @label, @sch, @tbl;
END
CLOSE t; DEALLOCATE t;
GO
