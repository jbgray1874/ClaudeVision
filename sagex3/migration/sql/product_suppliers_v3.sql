-- product_suppliers_v3.sql  -  READ ONLY, changes nothing
--
-- The full product-supplier list, in Sage codes, with every field Access holds that the
-- X3 product-supplier record can use.
--
-- What v2 showed:
--   STK_STOCK_2's ten part-supplier columns are empty, so purchase history is the only
--   source of who supplies what. 15,039 products have been bought; 17,050 of their 19,261
--   product-supplier pairs have a Sage supplier code.
--
-- Unlike the first list, this keeps EVERY supplier a product has been bought from, not
-- just the last one, ranked as priority 1, 2, 3. A product whose last supplier has no
-- Sage code still gets the others.
--
-- Run xref_sage_codes.sql and views_v2.sql first if their tables are not there.
-- Three grids. Grid 2 is the list (about 17,000 rows) - export it with Results To File,
-- tab delimited, and send it back.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#line') IS NOT NULL DROP TABLE #line;
SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           REPLACE(LTRIM(RTRIM(p.POR_PART_ONLY)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT                  AS product,
       CAST(LTRIM(RTRIM(p.POR_SUP_CODE)) AS varchar(20)) COLLATE DATABASE_DEFAULT AS access_supplier,
       p.POR_ORDER_DATE                                              AS order_date,
       p.POR_DUE_DATE                                                AS due_date,
       CAST(LTRIM(RTRIM(ISNULL(p.POR_CURR_CODE, ''))) AS varchar(4)) COLLATE DATABASE_DEFAULT AS currency,
       CAST(LTRIM(RTRIM(ISNULL(p.POR_UOM, ''))) AS varchar(10)) COLLATE DATABASE_DEFAULT     AS uom,
       CAST(ISNULL(p.POR_FORN_PRICE, 0) AS decimal(18, 5))           AS price_in_currency,
       CAST(ISNULL(p.POR_UOP_PRICE, 0) AS decimal(18, 5))            AS uop_price,
       CAST(ISNULL(p.POR_UOP_PRICE_PER, 0) AS decimal(18, 5))        AS uop_price_per,
       CAST(ISNULL(p.POR_QTY_ORDERED, 0) AS decimal(18, 4))          AS qty
INTO   #line
FROM   dbo.ASC_POR_TBL p
WHERE  LTRIM(RTRIM(ISNULL(p.POR_PART_ONLY, ''))) <> ''
  AND  LTRIM(RTRIM(ISNULL(p.POR_SUP_CODE, ''))) <> '';

IF OBJECT_ID('tempdb..#pair') IS NOT NULL DROP TABLE #pair;
WITH latest AS (
    SELECT l.*, ROW_NUMBER() OVER (PARTITION BY product, access_supplier
                                   ORDER BY order_date DESC) AS rn
    FROM #line l
), agg AS (
    SELECT product, access_supplier,
           COUNT(*)                     AS order_lines,
           CAST(SUM(qty) AS decimal(18, 2)) AS qty_ordered,
           MIN(order_date)              AS first_ordered,
           MAX(order_date)              AS last_ordered,
           AVG(CASE WHEN due_date >= order_date
                    THEN DATEDIFF(day, order_date, due_date) END) AS lead_time_days
    FROM #line
    GROUP BY product, access_supplier
)
SELECT a.*, t.currency, t.uom, t.price_in_currency, t.uop_price, t.uop_price_per,
       x.SAGE_CODE AS sage_supplier
INTO   #pair
FROM   agg a
JOIN   latest t ON t.product = a.product AND t.access_supplier = a.access_supplier AND t.rn = 1
LEFT JOIN migration.XREF_SAGE_BPS x ON x.ACCESS_CODE = a.access_supplier;

-- ===== 1. Size check =====
SELECT COUNT(*) AS product_supplier_pairs,
       COUNT(DISTINCT product) AS products,
       SUM(CASE WHEN sage_supplier IS NOT NULL THEN 1 ELSE 0 END) AS with_sage_supplier,
       COUNT(DISTINCT CASE WHEN sage_supplier IS NOT NULL THEN product END) AS products_with_one
FROM #pair;

-- ===== 2. THE LIST: every product and every Sage supplier it has been bought from =====
-- Priority 1 is the supplier last bought from. Export this grid to file.
SELECT p.product                                   AS product_code,
       p.sage_supplier                             AS supplier_code,
       ROW_NUMBER() OVER (PARTITION BY p.product
                          ORDER BY p.last_ordered DESC, p.order_lines DESC, p.sage_supplier) AS priority,
       ISNULL(n.SAGE_NAME, '')                     AS supplier_name,
       ISNULL(i.ITMDES, '')                        AS product_description,
       p.access_supplier,
       CASE WHEN p.currency IN ('', CHAR(163)) THEN 'GBP'           -- CHAR(163) is the pound sign
            WHEN p.currency = CHAR(128) THEN 'EUR'                  -- CHAR(128) is the euro sign
            WHEN p.currency = '$' THEN 'USD' ELSE p.currency END AS currency,
       p.uom                                       AS purchase_unit,
       p.price_in_currency                         AS last_price,
       p.uop_price, p.uop_price_per,
       p.lead_time_days,
       p.order_lines,
       p.qty_ordered,
       CONVERT(varchar(8), p.first_ordered, 112)   AS first_ordered,
       CONVERT(varchar(8), p.last_ordered, 112)    AS last_ordered
FROM #pair p
LEFT JOIN (SELECT SAGE_CODE, MIN(SAGE_NAME) AS SAGE_NAME
           FROM migration.SAGE_BPS_CODES GROUP BY SAGE_CODE) n
       ON n.SAGE_CODE = p.sage_supplier COLLATE DATABASE_DEFAULT
LEFT JOIN migration.ITM_LOOKUP i ON i.code = p.product
WHERE p.sage_supplier IS NOT NULL
ORDER BY p.product, priority;

-- ===== 3. Access suppliers with no Sage code, and the products only they supply =====
SELECT p.access_supplier, COUNT(DISTINCT p.product) AS products_only_from_them,
       CONVERT(varchar(8), MAX(p.last_ordered), 112) AS last_ordered
FROM #pair p
WHERE p.sage_supplier IS NULL
  AND NOT EXISTS (SELECT 1 FROM #pair o WHERE o.product = p.product AND o.sage_supplier IS NOT NULL)
GROUP BY p.access_supplier
ORDER BY 2 DESC;
GO
