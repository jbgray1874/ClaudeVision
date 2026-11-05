-- extract_accounts.sql  -  READ ONLY, changes nothing (temporary tables in tempdb only)
--
-- Every customer and supplier account for YA004BPC, YA004BPCDL and YA004BPS, live, in one run.
-- Until now those files were the 27 Oct build plus fixes; this lets the kit rebuild them whole
-- from the day's data (rule 1e). Bank details are NOT here: supplier_bank_details.sql, kept apart.
--
-- Grids (each starts with its label; text has tabs and line breaks replaced by spaces):
--   CHECK    as-at time and counts
--   XREFC    migration.XREF_SAGE_BPC: Sage code - Access code, every customer with a Sage code
--   XREFS    migration.XREF_SAGE_BPS: the same for suppliers
--   COLUMN   the columns of the three sources below, so their rows can be read by name
--   BPC      migration.vw_BPC for every customer in XREFC       (the customer file's source)
--   ADR      dbo.SL_ADDRESSES for those customers                (their addresses)
--   BPS      migration.vw_BPS for every supplier in XREFS       (the supplier file's source)
--   SUPVAT   PL_ACCOUNTS VAT / company numbers for those suppliers (fix_suppliers.py's check)
--   CUSVAT   every VAT number per customer: account and addresses (fill_customer_vat.py)
--   NEWC     live customers with NO Sage code: open items, open SO lines, or trade in 24 months
--   NEWS     the same for suppliers
-- NEWC / NEWS should be empty apart from the accounts left out on purpose. Any other row is an
-- account opened since 27 Oct that needs a Sage code before its orders and items can load.
--
-- Run after add_new_accounts_to_xref.sql. Results To File, tab delimited, one file, saved as
-- extract_accounts.txt and sent back. Expect a minute or two.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'CHECK' AS grid, 'as at' AS item, CONVERT(varchar(19), GETDATE(), 120) AS value
UNION ALL SELECT 'CHECK', 'customers in the cross-reference', CAST(COUNT(*) AS varchar(10)) FROM migration.XREF_SAGE_BPC
UNION ALL SELECT 'CHECK', 'suppliers in the cross-reference', CAST(COUNT(*) AS varchar(10)) FROM migration.XREF_SAGE_BPS;

SELECT 'XREFC' AS grid, LTRIM(RTRIM(SAGE_CODE)) AS sage, LTRIM(RTRIM(ACCESS_CODE)) AS access FROM migration.XREF_SAGE_BPC;
SELECT 'XREFS' AS grid, LTRIM(RTRIM(SAGE_CODE)) AS sage, LTRIM(RTRIM(ACCESS_CODE)) AS access FROM migration.XREF_SAGE_BPS;

-- the access codes, once
IF OBJECT_ID('tempdb..#c') IS NOT NULL DROP TABLE #c;
IF OBJECT_ID('tempdb..#s') IS NOT NULL DROP TABLE #s;
SELECT DISTINCT LTRIM(RTRIM(ACCESS_CODE)) COLLATE DATABASE_DEFAULT AS code INTO #c FROM migration.XREF_SAGE_BPC;
SELECT DISTINCT LTRIM(RTRIM(ACCESS_CODE)) COLLATE DATABASE_DEFAULT AS code INTO #s FROM migration.XREF_SAGE_BPS;

-- the three sources, whole rows, filtered to the codes; the code column of each view is its
-- second column (BPCNUM / the supplier code), found by position as new_supplier_details.sql does
IF OBJECT_ID('tempdb..#dump') IS NOT NULL DROP TABLE #dump;
CREATE TABLE #dump (label varchar(10), obj nvarchar(300), keycol sysname, codes sysname);
INSERT INTO #dump VALUES
    ('BPC', 'migration.vw_BPC', (SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('migration.vw_BPC') AND column_id = 2), '#c'),
    ('ADR', 'dbo.SL_ADDRESSES', 'AD_ACC_CODE', '#c'),
    ('BPS', 'migration.vw_BPS', (SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('migration.vw_BPS') AND column_id = 2), '#s');

SELECT 'COLUMN' AS grid, d.label, d.obj, c.column_id, c.name AS [column], ty.name AS type
FROM #dump d
JOIN sys.columns c ON c.object_id = OBJECT_ID(d.obj)
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
ORDER BY d.label, c.column_id;

DECLARE @label varchar(10), @obj nvarchar(300), @key sysname, @codes sysname, @cols nvarchar(max), @sql nvarchar(max);
DECLARE t CURSOR LOCAL FAST_FORWARD FOR SELECT label, obj, keycol, codes FROM #dump;
OPEN t;
FETCH NEXT FROM t INTO @label, @obj, @key, @codes;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @cols = STUFF((
        SELECT ', ' + CASE WHEN ty.name IN ('char', 'varchar', 'nchar', 'nvarchar', 'text', 'ntext')
                      THEN 'REPLACE(REPLACE(REPLACE(CAST(x.' + QUOTENAME(c.name) + ' AS nvarchar(max)), CHAR(9), '' ''), CHAR(13), '' ''), CHAR(10), '' '') AS ' + QUOTENAME(c.name)
                      ELSE 'x.' + QUOTENAME(c.name) END
        FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        WHERE c.object_id = OBJECT_ID(@obj)
          AND ty.name NOT IN ('image', 'varbinary', 'binary', 'timestamp', 'xml')
        ORDER BY c.column_id
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');
    SET @sql = N'SELECT ''' + @label + N''' AS grid, ' + @cols + N' FROM ' + @obj + N' x JOIN ' + @codes
             + N' k ON k.code = LTRIM(RTRIM(x.' + QUOTENAME(@key) + N')) COLLATE DATABASE_DEFAULT ORDER BY x.' + QUOTENAME(@key) + N';';
    EXEC sp_executesql @sql;
    FETCH NEXT FROM t INTO @label, @obj, @key, @codes;
END
CLOSE t; DEALLOCATE t;

-- supplier VAT and company numbers, as Access holds them
SELECT 'SUPVAT' AS grid, LTRIM(RTRIM(p.SUCODE)) AS access, LTRIM(RTRIM(ISNULL(p.SU_COUNTRY_CODE, ''))) AS country,
       REPLACE(LTRIM(RTRIM(ISNULL(p.SU_VAT_REG_NO, ''))), CHAR(9), ' ') AS vat,
       REPLACE(LTRIM(RTRIM(ISNULL(p.SU_COMPANY_REG_NUMBER, ''))), CHAR(9), ' ') AS company_reg
FROM dbo.PL_ACCOUNTS p JOIN #s k ON k.code = LTRIM(RTRIM(p.SUCODE)) COLLATE DATABASE_DEFAULT;

-- every customer VAT number (the customer_vat_numbers.sql grid, same columns)
SELECT 'CUSVAT' AS grid, LTRIM(RTRIM(x.SAGE_CODE)) AS sage, LTRIM(RTRIM(x.ACCESS_CODE)) AS access, v.*
FROM migration.XREF_SAGE_BPC x
CROSS APPLY (
    SELECT 'ACCOUNT' AS source, '' AS address_code, '' AS inv, '' AS stat, '' AS prim, '' AS country,
           REPLACE(LTRIM(RTRIM(a.CU_VAT_REG_NO)), CHAR(9), ' ') AS vat
    FROM dbo.SL_ACCOUNTS a
    WHERE LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(a.CU_VAT_REG_NO, ''))) <> ''
    UNION ALL
    SELECT 'ADDRESS', LTRIM(RTRIM(d.AD_CODE)), CAST(d.AD_INV_ADDRESS AS varchar(5)), CAST(d.AD_STAT_ADDRESS AS varchar(5)),
           CAST(d.SL_AD_PRIMARY AS varchar(5)), LTRIM(RTRIM(ISNULL(d.AD_COUNTRY_CODE, ''))),
           REPLACE(LTRIM(RTRIM(d.AD_VAT_REG_NO)), CHAR(9), ' ')
    FROM dbo.SL_ADDRESSES d
    WHERE LTRIM(RTRIM(d.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(d.AD_VAT_REG_NO, ''))) <> ''
    UNION ALL
    SELECT 'ADDRESS_COPYA', LTRIM(RTRIM(c.AD_CODE)), '', '', '', '', REPLACE(LTRIM(RTRIM(c.AD_VAT_REG_NO)), CHAR(9), ' ')
    FROM dbo.SL_ADDRESSES_COPYA c
    WHERE LTRIM(RTRIM(c.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(c.AD_VAT_REG_NO, ''))) <> ''
) v;

-- live accounts with no Sage code: what would be missed
WITH led AS (
    SELECT LTRIM(RTRIM(ST_COPYCUST)) COLLATE DATABASE_DEFAULT AS code, MAX(ST_DATE) AS last_entry,
           SUM(CASE WHEN ST_UNALLOCATED <> 0 THEN 1 ELSE 0 END) AS open_items,
           CAST(SUM(ST_UNALLOCATED) AS decimal(18, 2)) AS open_balance
    FROM dbo.SL_TRANSACTIONS GROUP BY LTRIM(RTRIM(ST_COPYCUST))
), ord AS (
    SELECT LTRIM(RTRIM(COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT AS code, MAX(COR_ORDER_DATE) AS last_order,
           SUM(CASE WHEN ISNULL(COR_QTY_ORDERED, 0) - ISNULL(COR_QTY_DELIVERED, 0) > 0 THEN 1 ELSE 0 END) AS open_lines
    FROM dbo.ASC_COR_TBL GROUP BY LTRIM(RTRIM(COR_CUSTOMER_CODE))
)
SELECT 'NEWC' AS grid, LTRIM(RTRIM(a.CUCODE)) AS access, REPLACE(LTRIM(RTRIM(a.CUNAME)), CHAR(9), ' ') AS name,
       CONVERT(varchar(10), l.last_entry, 23) AS last_ledger_entry, CONVERT(varchar(10), o.last_order, 23) AS last_order,
       ISNULL(l.open_items, 0) AS open_items, ISNULL(l.open_balance, 0) AS open_balance, ISNULL(o.open_lines, 0) AS open_so_lines
FROM dbo.SL_ACCOUNTS a
LEFT JOIN #c k ON k.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN led l ON l.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN ord o ON o.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
WHERE k.code IS NULL AND LTRIM(RTRIM(ISNULL(a.CUCODE, ''))) <> ''
  AND (ISNULL(l.open_items, 0) > 0 OR ISNULL(o.open_lines, 0) > 0
       OR l.last_entry >= DATEADD(month, -24, GETDATE()) OR o.last_order >= DATEADD(month, -24, GETDATE()))
ORDER BY open_items + open_so_lines DESC, access;

WITH led AS (
    SELECT LTRIM(RTRIM(PT_COPYSUPP)) COLLATE DATABASE_DEFAULT AS code, MAX(PT_DATE) AS last_entry,
           SUM(CASE WHEN PT_UNALLOCATED <> 0 THEN 1 ELSE 0 END) AS open_items,
           CAST(SUM(PT_UNALLOCATED) AS decimal(18, 2)) AS open_balance
    FROM dbo.PL_TRANSACTIONS GROUP BY LTRIM(RTRIM(PT_COPYSUPP))
), ord AS (
    SELECT LTRIM(RTRIM(POR_SUP_CODE)) COLLATE DATABASE_DEFAULT AS code, MAX(POR_ORDER_DATE) AS last_order,
           SUM(CASE WHEN ISNULL(POR_QTY_ORDERED, 0) - ISNULL(POR_QTY_DELIVERED, 0) - ISNULL(POR_QTY_REJECTED, 0) > 0
                    THEN 1 ELSE 0 END) AS open_lines
    FROM dbo.ASC_POR_TBL GROUP BY LTRIM(RTRIM(POR_SUP_CODE))
)
SELECT 'NEWS' AS grid, LTRIM(RTRIM(a.SUCODE)) AS access, REPLACE(LTRIM(RTRIM(a.SUNAME)), CHAR(9), ' ') AS name,
       CONVERT(varchar(10), l.last_entry, 23) AS last_ledger_entry, CONVERT(varchar(10), o.last_order, 23) AS last_order,
       ISNULL(l.open_items, 0) AS open_items, ISNULL(l.open_balance, 0) AS open_balance, ISNULL(o.open_lines, 0) AS open_po_lines
FROM dbo.PL_ACCOUNTS a
LEFT JOIN #s k ON k.code = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN led l ON l.code = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN ord o ON o.code = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
WHERE k.code IS NULL AND LTRIM(RTRIM(ISNULL(a.SUCODE, ''))) <> ''
  AND (ISNULL(l.open_items, 0) > 0 OR ISNULL(o.open_lines, 0) > 0 OR a.SU_DATE_INV >= DATEADD(month, -24, GETDATE())
       OR l.last_entry >= DATEADD(month, -24, GETDATE()) OR o.last_order >= DATEADD(month, -24, GETDATE()))
ORDER BY open_items + open_po_lines DESC, access;
GO
