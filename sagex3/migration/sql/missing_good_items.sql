-- missing_good_items.sql  -  READ ONLY, changes nothing
--
-- The item load was supposed to be GOOD + INCOMPLETE. It is not quite: products that
-- pass that test are missing from it, and they are on live orders and holding stock.
--
--   sales orders     70 lines on 52 GOOD products, 20 lines on 10 INCOMPLETE
--   purchase orders  32 lines on 26 GOOD products, 46 lines on 25 INCOMPLETE
--   stock            20 lots on 14 GOOD products, 66 lots on 38 INCOMPLETE - £45,245.08
--
-- That is not a policy decision anyone took. It needs no debate, only adding. This
-- lists exactly which products, ready to append to the item load.
--
-- It also shows the shape of the hole: LOAD_ITM holds 16,395 rows where GOOD +
-- INCOMPLETE is 16,241, so the two sets differ in BOTH directions. Grid 1 sizes that.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#itm') IS NOT NULL DROP TABLE #itm;
SELECT DISTINCT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT AS code
INTO   #itm FROM migration.LOAD_ITM;
CREATE CLUSTERED INDEX ix_i ON #itm(code);

IF OBJECT_ID('tempdb..#dq') IS NOT NULL DROP TABLE #dq;
SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
       CAST(MAX(LTRIM(RTRIM(ITMREF))) AS varchar(60)) COLLATE DATABASE_DEFAULT AS raw_code,
       CAST(MAX(DQ_STATUS) AS varchar(12)) COLLATE DATABASE_DEFAULT AS DQ_STATUS,
       CAST(MAX(LEFT(LTRIM(RTRIM(ISNULL(ITMDES1, ''))), 30)) AS varchar(30))
           COLLATE DATABASE_DEFAULT AS ITMDES1
INTO   #dq FROM migration.vw_DQ_ITM
GROUP BY UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'));
CREATE CLUSTERED INDEX ix_d ON #dq(code);

-- ===== 1. How far the item load and its own rule have drifted apart =====
SELECT 'products that are GOOD or INCOMPLETE' AS what, COUNT(*) AS n
FROM #dq WHERE DQ_STATUS IN ('GOOD', 'INCOMPLETE')
UNION ALL
SELECT 'of those, missing from the item load',
       SUM(CASE WHEN i.code IS NULL THEN 1 ELSE 0 END)
FROM #dq d LEFT JOIN #itm i ON i.code = d.code
WHERE d.DQ_STATUS IN ('GOOD', 'INCOMPLETE')
UNION ALL
SELECT 'codes in the item load', COUNT(*) FROM #itm
UNION ALL
SELECT 'of those, NOT GOOD or INCOMPLETE',
       SUM(CASE WHEN ISNULL(d.DQ_STATUS, 'x') NOT IN ('GOOD', 'INCOMPLETE') THEN 1 ELSE 0 END)
FROM #itm i LEFT JOIN #dq d ON d.code = i.code;

-- ===== 2. The ones that are actually in use: on an open order or holding stock =====
IF OBJECT_ID('tempdb..#inuse') IS NOT NULL DROP TABLE #inuse;
SELECT code, MAX(on_sales_order) AS on_sales_order, MAX(on_purchase_order) AS on_purchase_order,
       MAX(in_stock) AS in_stock, SUM(stock_value) AS stock_value
INTO #inuse
FROM (
    SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           1 AS on_sales_order, 0 AS on_purchase_order,
           0 AS in_stock, CAST(0 AS decimal(18,2)) AS stock_value
    FROM migration.vw_SOH_V2
    UNION ALL
    SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT, 0, 1, 0, 0 FROM migration.vw_POH_V2
    UNION ALL
    SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT, 0, 0, 1, REF_LOT_VALUE
    FROM migration.vw_SMR_V2
) z
GROUP BY code;
CREATE CLUSTERED INDEX ix_u ON #inuse(code);

SELECT d.DQ_STATUS,
       COUNT(*) AS products_to_add,
       SUM(u.on_sales_order) AS on_an_open_sales_order,
       SUM(u.on_purchase_order) AS on_an_open_purchase_order,
       SUM(u.in_stock) AS holding_stock,
       CAST(SUM(u.stock_value) AS decimal(18, 2)) AS stock_value
FROM #dq d
JOIN #inuse u ON u.code = d.code
LEFT JOIN #itm i ON i.code = d.code
WHERE i.code IS NULL AND d.DQ_STATUS IN ('GOOD', 'INCOMPLETE')
GROUP BY d.DQ_STATUS
ORDER BY d.DQ_STATUS;

-- ===== 3. The list itself. This is what to append to the item load =====
SELECT d.raw_code      AS access_code,
       d.code          AS sage_code,
       d.DQ_STATUS,
       d.ITMDES1       AS description,
       u.on_sales_order, u.on_purchase_order, u.in_stock,
       CAST(u.stock_value AS decimal(18, 2)) AS stock_value
FROM #dq d
JOIN #inuse u ON u.code = d.code
LEFT JOIN #itm i ON i.code = d.code
WHERE i.code IS NULL AND d.DQ_STATUS IN ('GOOD', 'INCOMPLETE')
ORDER BY d.DQ_STATUS, d.raw_code;

-- ===== 4. And the stock sitting on products with no activity in five years =====
-- £441,136.27 across 1,554 lots. Not a migration question - a stock provision one.
SELECT TOP 25 v.ITMREF, LEFT(ISNULL(d.ITMDES1, ''), 30) AS description,
       COUNT(*) AS lots,
       CAST(SUM(v.REF_LOT_VALUE) AS decimal(18, 2)) AS stock_value
FROM migration.vw_SMR_V2 v
LEFT JOIN #itm i ON i.code = v.ITMREF COLLATE DATABASE_DEFAULT
LEFT JOIN #dq  d ON d.code = v.ITMREF COLLATE DATABASE_DEFAULT
WHERE i.code IS NULL AND d.DQ_STATUS = 'OLD'
GROUP BY v.ITMREF, LEFT(ISNULL(d.ITMDES1, ''), 30)
ORDER BY stock_value DESC;
GO
