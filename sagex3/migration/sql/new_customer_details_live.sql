-- new_customer_details_live.sql  -  READ ONLY, changes nothing (temporary tables in tempdb only)
--
-- The live version of new_customer_details.sql (which held a fixed list of 27 Oct codes).
-- Every live Access customer with NO Sage code in migration.XREF_SAGE_BPC that has open items,
-- open sales-order lines, or traded in the last 24 months - the same rule as extract_accounts.sql's
-- NEWC grid (18 Nov: 37 accounts, among them AFB01, MUN01, TDG03, BWS01, KOM01, whose late-October
-- invoices were missing from the 4 Nov extract for exactly this reason).
--
-- Grid 1: their migration.vw_BPC rows        (scripts/build_new_customers.py grid 1)
-- Grid 2: their dbo.SL_ADDRESSES rows        (grid 2)
-- Grid 3: the check - accounts listed, and how many vw_BPC holds
--
-- Run the whole file. Results To File, tab delimited, saved as new_customer_details_live.txt.
USE SDILive;
GO
SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#codes') IS NOT NULL DROP TABLE #codes;

WITH led AS (
    SELECT LTRIM(RTRIM(ST_COPYCUST)) COLLATE DATABASE_DEFAULT AS code, MAX(ST_DATE) AS last_entry,
           SUM(CASE WHEN ST_UNALLOCATED <> 0 THEN 1 ELSE 0 END) AS open_items
    FROM dbo.SL_TRANSACTIONS GROUP BY LTRIM(RTRIM(ST_COPYCUST))
), ord AS (
    SELECT LTRIM(RTRIM(COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT AS code, MAX(COR_ORDER_DATE) AS last_order,
           SUM(CASE WHEN ISNULL(COR_QTY_ORDERED, 0) - ISNULL(COR_QTY_DELIVERED, 0) > 0 THEN 1 ELSE 0 END) AS open_lines
    FROM dbo.ASC_COR_TBL GROUP BY LTRIM(RTRIM(COR_CUSTOMER_CODE))
)
SELECT DISTINCT LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT AS code
INTO #codes
FROM dbo.SL_ACCOUNTS a
LEFT JOIN migration.XREF_SAGE_BPC x ON LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN led l ON l.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN ord o ON o.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
WHERE x.ACCESS_CODE IS NULL AND LTRIM(RTRIM(ISNULL(a.CUCODE, ''))) <> ''
  AND (ISNULL(l.open_items, 0) > 0 OR ISNULL(o.open_lines, 0) > 0
       OR l.last_entry >= DATEADD(month, -24, GETDATE()) OR o.last_order >= DATEADD(month, -24, GETDATE()));

SELECT b.*
FROM migration.vw_BPC b
JOIN #codes k ON k.code = LTRIM(RTRIM(b.BPCNUM)) COLLATE DATABASE_DEFAULT
ORDER BY b.BPCNUM;

SELECT a.*
FROM dbo.SL_ADDRESSES a
JOIN #codes k ON k.code = LTRIM(RTRIM(a.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT
ORDER BY a.AD_ACC_CODE, a.AD_CODE;

SELECT (SELECT COUNT(*) FROM #codes) AS codes_listed,
       (SELECT COUNT(DISTINCT LTRIM(RTRIM(b.BPCNUM))) FROM migration.vw_BPC b
         JOIN #codes k ON k.code = LTRIM(RTRIM(b.BPCNUM)) COLLATE DATABASE_DEFAULT) AS customers_in_vw_BPC;
GO
