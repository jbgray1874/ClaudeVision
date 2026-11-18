-- supplier_emails.sql  -  READ ONLY, changes nothing.  Run against SDILive.
--
-- Claire, 18 Nov: add the suppliers' email addresses from Access (Address / Contact tab,
-- "Email (Statements)") to Finance's supplier list, because remittances are bouncing.
--
-- We don't hard-code the column name: this finds every text column, in every PL_ table keyed by
-- supplier (PL_ACCOUNTS, PL_ADDRESSES, ...), that holds an '@' for a supplier, and lists it with
-- the table and column it came from. scripts/fill_supplier_emails.py then fills the list.
--
-- Results to File, tab delimited, WITH column headers: <folder>/supplier_emails.txt
-- (or Results to Grid, select all, Copy with Headers, paste into a .txt file).
--
-- Grids:
--   SUMMARY  how many suppliers have an email in each table / column (to see which is "Statements")
--   EMAIL    one row per supplier, table, column, value

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#e') IS NOT NULL DROP TABLE #e;
CREATE TABLE #e (access_code nvarchar(50), tbl sysname, col sysname, value nvarchar(4000));

DECLARE @sql nvarchar(max) = N'';

SELECT @sql = @sql + CASE WHEN @sql = N'' THEN N'' ELSE N' UNION ALL ' END
    + N'SELECT LTRIM(RTRIM(CAST(x.' + QUOTENAME(k.keycol) + N' AS nvarchar(50)))), '''
    + t.name + N''', ''' + c.name + N''', '
    + N'LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CAST(x.' + QUOTENAME(c.name)
    + N' AS nvarchar(4000)), CHAR(9), '' ''), CHAR(13), '' ''), CHAR(10), '' '')))'
    + N' FROM dbo.' + QUOTENAME(t.name) + N' x'
    + N' WHERE CAST(x.' + QUOTENAME(c.name) + N' AS nvarchar(4000)) LIKE ''%@%'''
FROM sys.tables t
JOIN sys.columns c   ON c.object_id = t.object_id
JOIN sys.types ty    ON ty.user_type_id = c.user_type_id
CROSS APPLY (SELECT TOP 1 kc.name AS keycol
             FROM sys.columns kc
             WHERE kc.object_id = t.object_id
               AND kc.name IN ('SUCODE', 'AD_ACC_CODE', 'SU_CODE')
             ORDER BY CASE kc.name WHEN 'SUCODE' THEN 1 WHEN 'AD_ACC_CODE' THEN 2 ELSE 3 END) k
WHERE SCHEMA_NAME(t.schema_id) = 'dbo'
  AND t.name LIKE 'PL[_]%'
  AND ty.name IN ('char', 'varchar', 'nchar', 'nvarchar', 'text', 'ntext');

IF @sql <> N''
    INSERT INTO #e (access_code, tbl, col, value) EXEC sp_executesql @sql;

SELECT 'SUMMARY' AS grid, tbl, col, COUNT(DISTINCT access_code) AS suppliers, COUNT(*) AS rows_found
FROM #e
GROUP BY tbl, col
ORDER BY suppliers DESC;

SELECT 'EMAIL' AS grid, access_code, tbl, col, value
FROM #e
ORDER BY access_code, tbl, col;
