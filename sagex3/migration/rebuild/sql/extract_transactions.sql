-- extract_transactions.sql  -  READ ONLY, changes nothing.
--
-- The live opening transactions for the six YA004 files, in one run, each grid labelled:
--   CHECK   new accounts in the cross-reference (86 / 83) and rows the views drop for want of an
--           account - STOP if not 0 or only the accounts left out on purpose
--   TOTALS  control totals for the reconciliation: items and GBP per ledger, stock lots and value
--   SOH     open sales orders       -> YA004SOHPJ     (migration.vw_SOH_V2)
--   POH     open purchase orders    -> YA004POH       (migration.vw_POH_V2)
--   SMR     opening stock           -> YA004SMR       (migration.vw_SMR_V2)
--   BICX    customer open items     -> YA004BICY      (migration.vw_BICX_V2)
--   BISX    supplier open items     -> YA004BISY      (migration.vw_BISX_V2)
--   WOR     open works orders       -> YA004MFG       (ASC_WOR_TBL, as works_orders_extract.sql)
--
-- Before it, on the same morning (each changes only our own migration objects):
--   1. sql/add_new_accounts_to_xref.sql   - the 86 + 83 accounts added on 27 Oct
--   2. sql/views_v2.sql                   - the views this reads, current definitions
-- Every extract is taken from live data on the day of the run (runbook, rule 1).
--
-- Results To File, tab delimited, ONE file: <run>/extract/extract_transactions.txt.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'CHECK' AS grid, 'as at' AS [check], CONVERT(varchar(19), GETDATE(), 120) AS value
UNION ALL
SELECT 'CHECK', 'new customer accounts in the cross-reference', CAST(COUNT(*) AS varchar(19))
FROM migration.XREF_SAGE_BPC WHERE MATCHED_BY = 'new account'
UNION ALL
SELECT 'CHECK', 'new supplier accounts in the cross-reference', CAST(COUNT(*) AS varchar(19))
FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account'
UNION ALL
SELECT 'CHECK', 'SOH lines dropped - customer has no Sage account', CAST(COUNT(*) AS varchar(19))
FROM dbo.ASC_COR_TBL c
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT
WHERE c.COR_QTY_ORDERED - ISNULL(c.COR_QTY_DELIVERED, 0) > 0
  AND ISNULL(c.COR_ORDER_STATUS, '') IN ('', 'B', 'H')
  AND LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_CODE, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'CHECK', 'POH lines dropped - supplier has no Sage account', CAST(COUNT(*) AS varchar(19))
FROM dbo.ASC_POR_TBL p
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(p.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT
WHERE p.POR_QTY_ORDERED - ISNULL(p.POR_QTY_DELIVERED, 0) - ISNULL(p.POR_QTY_REJECTED, 0) > 0
  AND LTRIM(RTRIM(ISNULL(p.POR_SUP_CODE, ''))) <> '' AND xs.SAGE_CODE IS NULL
UNION ALL
SELECT 'CHECK', 'BICX items dropped - customer has no Sage account', CAST(COUNT(*) AS varchar(19))
FROM dbo.SL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(t.ST_COPYCUST)) COLLATE DATABASE_DEFAULT
WHERE t.ST_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.ST_COPYCUST, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'CHECK', 'BISX items dropped - supplier has no Sage account', CAST(COUNT(*) AS varchar(19))
FROM dbo.PL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(t.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT
WHERE t.PT_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.PT_COPYSUPP, ''))) <> '' AND xs.SAGE_CODE IS NULL;

SELECT 'TOTALS' AS grid, 'customer open items' AS what, COUNT(*) AS items, CAST(SUM(GBPAmount) AS decimal(18, 2)) AS gbp
FROM migration.vw_BICX_V2
UNION ALL
SELECT 'TOTALS', 'supplier open items', COUNT(*), CAST(SUM(GBPAmount) AS decimal(18, 2)) FROM migration.vw_BISX_V2
UNION ALL
SELECT 'TOTALS', 'opening stock (lots, value)', COUNT(*), CAST(SUM(REF_LOT_VALUE) AS decimal(18, 2)) FROM migration.vw_SMR_V2
UNION ALL
SELECT 'TOTALS', 'open sales order lines', COUNT(*), NULL FROM migration.vw_SOH_V2
UNION ALL
SELECT 'TOTALS', 'open purchase order lines', COUNT(*), NULL FROM migration.vw_POH_V2;

SELECT 'SOH' AS grid, * FROM migration.vw_SOH_V2;
SELECT 'POH' AS grid, * FROM migration.vw_POH_V2;
SELECT 'SMR' AS grid, * FROM migration.vw_SMR_V2;
SELECT 'BICX' AS grid, * FROM migration.vw_BICX_V2;
SELECT 'BISX' AS grid, * FROM migration.vw_BISX_V2;

SELECT 'WOR' AS grid,
       WOR_UNIQUE,
       LTRIM(RTRIM(WOR_ORDER))        AS works_order,
       LTRIM(RTRIM(WOR_PARENT_ORDER)) AS parent_order,
       LTRIM(RTRIM(WOR_ITEM_ONLY))    AS product,
       LTRIM(RTRIM(WOR_ITEM_REV))     AS rev,
       LTRIM(RTRIM(WOR_SALORD))       AS sales_order,
       LTRIM(RTRIM(WOR_CUSTOMER))     AS customer,
       RTRIM(WOR_ORDER_TYPE)          AS order_type,
       CAST(WOR_ORIG_QTY AS decimal(18, 3))     AS orig_qty,
       CAST(WOR_AMD_QTY AS decimal(18, 3))      AS amd_qty,
       CAST(WOR_GOOD_QTY AS decimal(18, 3))     AS good_qty,
       CAST(WOR_REJECTED_QTY AS decimal(18, 3)) AS rejected_qty,
       CAST(WOR_SCRAP_QTY AS decimal(18, 3))    AS scrap_qty,
       CONVERT(varchar(8), WOR_CREATED_DATE, 112)      AS created,
       CONVERT(varchar(8), WOR_FIRST_DATE, 112)        AS first_date,
       CONVERT(varchar(8), WOR_MRP_DATE, 112)          AS mrp_date,
       CONVERT(varchar(8), WOR_DATE_SCHED, 112)        AS scheduled,
       CONVERT(varchar(8), WOR_LAST_MAT_DUE_DATE, 112) AS last_mat_due,
       CONVERT(varchar(8), WOR_DONE_DATE, 112)         AS done_date,
       RTRIM(WOR_MAT_STAT)            AS mat_stat,
       CAST(WOR_BOOKED_MAT_COST AS decimal(18, 2)) AS booked_mat,
       CAST(WOR_BOOKED_LAB_COST AS decimal(18, 2)) AS booked_lab,
       CAST(WOR_BOOKED_SC_COST AS decimal(18, 2))  AS booked_subcon,
       LTRIM(RTRIM(WOR_DEST_WH))      AS dest_wh,
       LTRIM(RTRIM(WOR_DEST_BIN))     AS dest_bin
FROM dbo.ASC_WOR_TBL
WHERE LTRIM(RTRIM(ISNULL(WOR_STATUS, ''))) = ''
ORDER BY WOR_DATE_SCHED, WOR_ORDER;
GO
