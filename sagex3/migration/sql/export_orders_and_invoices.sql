-- export_orders_and_invoices.sql  -  READ ONLY, changes nothing
--
-- The rows for the four opening-transaction files, now that the cross-reference holds the
-- new customer and supplier codes (add_new_accounts_to_xref.sql). The views read the
-- cross-reference when they run, so nothing needs rebuilding first - not views_v2.sql either.
--
-- Five grids. Results To File, tab delimited, one file, and send it back.
--   1  check: new accounts in the cross-reference (should be 86 and 83), and rows still
--      dropped for want of an account (should be 0, or only the accounts left out on purpose)
--   2  open sales orders      (YA004SOHPJ)
--   3  open purchase orders   (YA004POH)
--   4  customer open items    (YA004BICX)
--   5  supplier open items    (YA004BISX)
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'new customer accounts in the cross-reference' AS [check], COUNT(*) AS value
FROM migration.XREF_SAGE_BPC WHERE MATCHED_BY = 'new account'
UNION ALL
SELECT 'new supplier accounts in the cross-reference', COUNT(*)
FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account'
UNION ALL
SELECT 'SOH lines still dropped - customer has no Sage account', COUNT(*)
FROM dbo.ASC_COR_TBL c
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT
WHERE c.COR_QTY_ORDERED - ISNULL(c.COR_QTY_DELIVERED, 0) > 0
  AND ISNULL(c.COR_ORDER_STATUS, '') IN ('', 'B', 'H')
  AND LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_CODE, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'POH lines still dropped - supplier has no Sage account', COUNT(*)
FROM dbo.ASC_POR_TBL p
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(p.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT
WHERE p.POR_QTY_ORDERED - ISNULL(p.POR_QTY_DELIVERED, 0) - ISNULL(p.POR_QTY_REJECTED, 0) > 0
  AND LTRIM(RTRIM(ISNULL(p.POR_SUP_CODE, ''))) <> '' AND xs.SAGE_CODE IS NULL
UNION ALL
SELECT 'BICX items still dropped - customer has no Sage account', COUNT(*)
FROM dbo.SL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(t.ST_COPYCUST)) COLLATE DATABASE_DEFAULT
WHERE t.ST_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.ST_COPYCUST, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'BISX items still dropped - supplier has no Sage account', COUNT(*)
FROM dbo.PL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(t.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT
WHERE t.PT_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.PT_COPYSUPP, ''))) <> '' AND xs.SAGE_CODE IS NULL;

SELECT * FROM migration.vw_SOH_V2;
SELECT * FROM migration.vw_POH_V2;
SELECT * FROM migration.vw_BICX_V2;
SELECT * FROM migration.vw_BISX_V2;
GO
