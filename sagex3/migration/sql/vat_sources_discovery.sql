-- vat_sources_discovery.sql  -  READ ONLY, changes nothing (temporary tables in tempdb only)
--
-- The users say Access holds VAT numbers that the supplier file doesn't have (4 Nov). Our builds
-- read PL_ACCOUNTS.SU_VAT_REG_NO and SL_ACCOUNTS.CU_VAT_REG_NO only. This looks everywhere:
--   1  COLUMNS  every column in the database whose name suggests a VAT or registration number,
--               with the table's row count
--   2  FILLED   for each of them, how many rows hold a value, and three examples
--   3  SUPPLIER every supplier's own VAT and registration fields in PL_ACCOUNTS, all suppliers,
--               so the blanks in the supplier file can be filled from whichever field has it
-- Grid 2 reads only the columns grid 1 finds, one at a time. Expect a minute.
--
-- Results To File, tab delimited, one file, and send it back. Each grid starts with a label.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#cols') IS NOT NULL DROP TABLE #cols;
SELECT s.name AS sch, t.name AS tbl, c.name AS col, ty.name AS typ,
       (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = t.object_id AND p.index_id IN (0, 1)) AS tbl_rows
INTO   #cols
FROM   sys.tables t
JOIN   sys.schemas s ON s.schema_id = t.schema_id
JOIN   sys.columns c ON c.object_id = t.object_id
JOIN   sys.types ty ON ty.user_type_id = c.user_type_id
WHERE  s.name = 'dbo'
  AND  ty.name IN ('varchar', 'nvarchar', 'char', 'nchar')
  AND  (c.name LIKE '%VAT%' OR c.name LIKE '%TAX_REG%' OR c.name LIKE '%TAXREG%' OR c.name LIKE '%EORI%'
        OR c.name LIKE '%SIRET%' OR c.name LIKE '%SIREN%' OR c.name LIKE '%COMPANY_REG%' OR c.name LIKE '%CO_REG%'
        OR c.name LIKE '%REG_NO%' OR c.name LIKE '%REGNO%' OR c.name LIKE '%EC_NO%' OR c.name LIKE '%ECNO%');

SELECT 'COLUMNS' AS grid, tbl, col, typ, tbl_rows FROM #cols ORDER BY tbl, col;

-- 2. how many rows hold a value in each, with examples (dynamic, one column at a time)
IF OBJECT_ID('tempdb..#filled') IS NOT NULL DROP TABLE #filled;
CREATE TABLE #filled (tbl sysname, col sysname, filled int, distinct_values int, ex1 nvarchar(60), ex2 nvarchar(60),
                      ex3 nvarchar(60));
DECLARE @t sysname, @c sysname, @sql nvarchar(max);
DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT tbl, col FROM #cols;
OPEN cur;
FETCH NEXT FROM cur INTO @t, @c;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'INSERT INTO #filled
        SELECT @t, @c, COUNT(*), COUNT(DISTINCT v),
               MIN(v), MAX(v), MIN(CASE WHEN v > MIN_v THEN v END)
        FROM (SELECT LTRIM(RTRIM(CAST(' + QUOTENAME(@c) + N' AS nvarchar(60)))) AS v,
                     MIN(LTRIM(RTRIM(CAST(' + QUOTENAME(@c) + N' AS nvarchar(60))))) OVER () AS MIN_v
              FROM dbo.' + QUOTENAME(@t) + N'
              WHERE LTRIM(RTRIM(ISNULL(CAST(' + QUOTENAME(@c) + N' AS nvarchar(60)), ''''))) NOT IN ('''', ''0'')) z;';
    EXEC sp_executesql @sql, N'@t sysname, @c sysname', @t = @t, @c = @c;
    FETCH NEXT FROM cur INTO @t, @c;
END
CLOSE cur;
DEALLOCATE cur;

SELECT 'FILLED' AS grid, tbl, col, filled, distinct_values,
       ISNULL(ex1, '') AS example_1, ISNULL(ex2, '') AS example_2, ISNULL(ex3, '') AS example_3
FROM #filled ORDER BY filled DESC;

-- 3. every supplier's own VAT and registration fields
SELECT 'SUPPLIER' AS grid,
       LTRIM(RTRIM(p.SUCODE))                                   AS access_code,
       ISNULL(x.SAGE_CODE, '')                                  AS sage_code,
       LTRIM(RTRIM(ISNULL(p.SU_COUNTRY_CODE, '')))              AS country,
       LTRIM(RTRIM(ISNULL(p.SU_VAT_REG_NO, '')))                AS vat_reg_no,
       LTRIM(RTRIM(ISNULL(p.SU_COMPANY_REG_NUMBER, '')))        AS company_reg_number,
       LTRIM(RTRIM(ISNULL(p.SU_CIS_COMPANY_REG_NO, '')))        AS cis_company_reg_no,
       LTRIM(RTRIM(ISNULL(p.SU_TAX_CODE, '')))                  AS tax_code
FROM   dbo.PL_ACCOUNTS p
LEFT JOIN migration.XREF_SAGE_BPS x
       ON x.ACCESS_CODE COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(p.SUCODE)) COLLATE DATABASE_DEFAULT
ORDER BY p.SUCODE;
GO
