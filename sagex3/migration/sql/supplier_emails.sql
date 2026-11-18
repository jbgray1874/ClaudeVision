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
--   SAGE     Access supplier code -> new Sage code (migration.XREF_SAGE_BPS): Claire's column A
--   TAX      every VAT / tax column on PL_ACCOUNTS, per supplier: Claire's column G (VAT code)
--
-- Bank details are NOT read here: run sql/supplier_bank_details.sql as well (confidential output,
-- kept in the private bank folder), and pass it to fill_supplier_emails.py --bank.

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

SELECT 'SAGE' AS grid, LTRIM(RTRIM(x.ACCESS_CODE)) AS access_code, LTRIM(RTRIM(x.SAGE_CODE)) AS sage_code, '' AS c3, '' AS c4
FROM migration.XREF_SAGE_BPS x
ORDER BY access_code;

-- VAT / tax columns on PL_ACCOUNTS, found by name (VAT or TAX), one row per supplier and column
IF OBJECT_ID('tempdb..#t') IS NOT NULL DROP TABLE #t;
CREATE TABLE #t (access_code nvarchar(50), col sysname, value nvarchar(400));
DECLARE @tsql nvarchar(max) = N'';
SELECT @tsql = @tsql + CASE WHEN @tsql = N'' THEN N'' ELSE N' UNION ALL ' END
    + N'SELECT LTRIM(RTRIM(CAST(x.SUCODE AS nvarchar(50)))), ''' + c.name + N''', '
    + N'LTRIM(RTRIM(CAST(x.' + QUOTENAME(c.name) + N' AS nvarchar(400)))) FROM dbo.PL_ACCOUNTS x'
    + N' WHERE LTRIM(RTRIM(ISNULL(CAST(x.' + QUOTENAME(c.name) + N' AS nvarchar(400)), ''''))) <> '''''
FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dbo.PL_ACCOUNTS')
  AND (c.name LIKE '%VAT%' OR c.name LIKE '%TAX%')
  AND ty.name NOT IN ('image', 'varbinary', 'binary', 'timestamp', 'xml');
IF @tsql <> N'' INSERT INTO #t (access_code, col, value) EXEC sp_executesql @tsql;

SELECT 'TAX' AS grid, access_code, col, value, '' AS c4
FROM #t
ORDER BY access_code, col;

