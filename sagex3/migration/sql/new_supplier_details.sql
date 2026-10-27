-- new_supplier_details.sql  -  READ ONLY, changes nothing
--
-- Live Access suppliers with no Sage X3 code, and their details, in one go.
-- The supplier side of new_customer_details.sql: open purchase invoices (BISX), open purchase
-- order lines (POH) and product-supplier links (ZSDIITMSUP) for these suppliers are dropped
-- by the views until they have a code.
--
-- "Live" = open invoices, OR open order lines, OR invoiced / ordered in the last 24 months.
--
-- Run xref_sage_codes.sql (version 3) first. Run the whole file. Results To File, tab
-- delimited, and send it back. Three grids:
--   1  the suppliers, with why they matter (open items, open PO lines, last dates)
--   2  their rows in migration.vw_BPS, the view the supplier import was built from
--   3  a check: suppliers listed and suppliers found in vw_BPS should be the same
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#missing') IS NOT NULL DROP TABLE #missing;

WITH ledger AS (
    SELECT LTRIM(RTRIM(PT_COPYSUPP)) COLLATE DATABASE_DEFAULT AS code,
           MAX(PT_DATE) AS last_ledger_entry,
           SUM(CASE WHEN PT_UNALLOCATED <> 0 THEN 1 ELSE 0 END) AS open_items,
           CAST(SUM(PT_UNALLOCATED) AS decimal(18, 2)) AS open_balance
    FROM dbo.PL_TRANSACTIONS
    GROUP BY LTRIM(RTRIM(PT_COPYSUPP))
), orders AS (
    SELECT LTRIM(RTRIM(POR_SUP_CODE)) COLLATE DATABASE_DEFAULT AS code,
           MAX(POR_ORDER_DATE) AS last_order,
           SUM(CASE WHEN ISNULL(POR_QTY_ORDERED, 0) - ISNULL(POR_QTY_DELIVERED, 0) - ISNULL(POR_QTY_REJECTED, 0) > 0
                    THEN 1 ELSE 0 END) AS open_lines,
           COUNT(DISTINCT CASE WHEN POR_ORDER_DATE >= DATEADD(month, -24, GETDATE())
                               THEN LTRIM(RTRIM(POR_PART_ONLY)) END) AS products_24m
    FROM dbo.ASC_POR_TBL
    GROUP BY LTRIM(RTRIM(POR_SUP_CODE))
), dupname AS (
    SELECT UPPER(LTRIM(RTRIM(SUNAME))) COLLATE DATABASE_DEFAULT AS nm
    FROM dbo.PL_ACCOUNTS
    GROUP BY UPPER(LTRIM(RTRIM(SUNAME)))
    HAVING COUNT(*) > 1
)
SELECT LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT AS access_code,
       LTRIM(RTRIM(a.SUNAME))                          AS supplier_name,
       LTRIM(RTRIM(ISNULL(a.SU_COUNTRY_CODE, '')))     AS country,
       CASE WHEN UPPER(LTRIM(RTRIM(a.SUNAME))) LIKE 'SDI DISPLAYS%' THEN 'Intercompany (SDI entity)'
            WHEN d.nm IS NOT NULL THEN 'Same name as another supplier account'
            ELSE '' END                                AS note,
       CONVERT(varchar(10), a.SU_DATE_INV, 23)         AS last_invoice,
       CONVERT(varchar(10), o.last_order, 23)          AS last_order,
       CONVERT(varchar(10), l.last_ledger_entry, 23)   AS last_ledger_entry,
       ISNULL(l.open_items, 0)                         AS open_items,
       ISNULL(l.open_balance, 0)                       AS open_balance,
       ISNULL(o.open_lines, 0)                         AS open_po_lines,
       ISNULL(o.products_24m, 0)                       AS products_bought_24m
INTO #missing
FROM dbo.PL_ACCOUNTS a
LEFT JOIN migration.XREF_SAGE_BPS x ON x.ACCESS_CODE = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN ledger  l ON l.code = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN orders  o ON o.code = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN dupname d ON d.nm   = UPPER(LTRIM(RTRIM(a.SUNAME))) COLLATE DATABASE_DEFAULT
WHERE x.SAGE_CODE IS NULL
  AND LTRIM(RTRIM(ISNULL(a.SUCODE, ''))) <> ''
  AND (   ISNULL(l.open_items, 0) > 0
       OR ISNULL(o.open_lines, 0) > 0
       OR a.SU_DATE_INV        >= DATEADD(month, -24, GETDATE())
       OR o.last_order         >= DATEADD(month, -24, GETDATE())
       OR l.last_ledger_entry  >= DATEADD(month, -24, GETDATE()));

-- 1. the suppliers
SELECT * FROM #missing
ORDER BY open_items + open_po_lines DESC, access_code;

-- 2. their vw_BPS rows. The supplier code is the view's second column (as BPCNUM is in
--    vw_BPC), found by position so this does not depend on its name.
DECLARE @code sysname = (SELECT name FROM sys.columns
                         WHERE object_id = OBJECT_ID('migration.vw_BPS') AND column_id = 2);
DECLARE @sql nvarchar(max) =
    N'SELECT b.* FROM migration.vw_BPS b JOIN #missing m ON m.access_code = LTRIM(RTRIM(b.'
    + QUOTENAME(@code) + N')) COLLATE DATABASE_DEFAULT ORDER BY b.' + QUOTENAME(@code) + N';'
  + N' SELECT (SELECT COUNT(*) FROM #missing) AS suppliers_listed,'
  + N' (SELECT COUNT(DISTINCT LTRIM(RTRIM(b.' + QUOTENAME(@code) + N'))) FROM migration.vw_BPS b'
  + N'  JOIN #missing m ON m.access_code = LTRIM(RTRIM(b.' + QUOTENAME(@code) + N')) COLLATE DATABASE_DEFAULT)'
  + N' AS found_in_vw_BPS, ''' + @code + N''' AS code_column;';
EXEC sp_executesql @sql;
GO
