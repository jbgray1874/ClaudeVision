-- preferred_customer_by_product.sql  -  READ ONLY, changes nothing
--
-- The customer equivalent of the preferred-supplier list Marc asked for: product code
-- and customer code in one sheet.
--
-- Unlike last time, this does the whole job in SQL. The supplier list had to come back
-- in Access codes and be translated outside the database, because the Sage codes only
-- existed in the load files. migration.XREF_SAGE_BPC now holds that mapping, so the
-- codes come out of here ready to send - Sage product code, Sage customer code.
--
-- "Preferred customer" is derived from sales history: the customer a product was most
-- recently sold to. SDI's products are largely customer-specific anyway - TES-, MS-,
-- BOT- - so most will have only ever had one. Grid 2 carries a column saying which.
--
-- Run xref_sage_codes.sql first if it has not been run in this session.
-- Six grids. Grid 2 is the sheet; export it with Results To File.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. The size of what we are working from =====
SELECT COUNT(*) AS order_lines,
       COUNT(DISTINCT LTRIM(RTRIM(COR_PART_ONLY))) AS products,
       COUNT(DISTINCT LTRIM(RTRIM(COR_CUSTOMER_CODE))) AS customers,
       CAST(MIN(COR_ORDER_DATE) AS date) AS oldest,
       CAST(MAX(COR_ORDER_DATE) AS date) AS newest
FROM dbo.ASC_COR_TBL
WHERE LTRIM(RTRIM(ISNULL(COR_PART_ONLY, ''))) <> ''
  AND LTRIM(RTRIM(ISNULL(COR_CUSTOMER_CODE, ''))) <> ''
  AND COR_ORDER_DATE >= '20220901';

IF OBJECT_ID('tempdb..#pair') IS NOT NULL DROP TABLE #pair;
SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(c.COR_PART_ONLY)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT              AS part,
       CAST(LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) AS varchar(20))
           COLLATE DATABASE_DEFAULT                              AS access_customer,
       COUNT(*)                                                  AS order_lines,
       CAST(SUM(c.COR_QTY_ORDERED) AS decimal(18, 2))            AS qty_ordered,
       MAX(c.COR_ORDER_DATE)                                     AS last_ordered
INTO   #pair
FROM   dbo.ASC_COR_TBL c
WHERE  LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> ''
  AND  LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_CODE, ''))) <> ''
  AND  c.COR_ORDER_DATE >= '20220901'
GROUP BY CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(c.COR_PART_ONLY)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)),
         CAST(LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) AS varchar(20));
CREATE CLUSTERED INDEX ix_pair ON #pair(part);

IF OBJECT_ID('tempdb..#best') IS NOT NULL DROP TABLE #best;
SELECT part, access_customer, order_lines, qty_ordered, last_ordered,
       customers_ever_used
INTO   #best
FROM (
    SELECT p.*,
           ROW_NUMBER() OVER (PARTITION BY p.part
                              ORDER BY p.last_ordered DESC, p.order_lines DESC,
                                       p.access_customer) AS rn,
           COUNT(*) OVER (PARTITION BY p.part) AS customers_ever_used
    FROM #pair p
) z
WHERE rn = 1;
CREATE CLUSTERED INDEX ix_best ON #best(part);

IF OBJECT_ID('tempdb..#itm') IS NOT NULL DROP TABLE #itm;
SELECT DISTINCT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT AS code
INTO   #itm FROM migration.LOAD_ITM;
CREATE CLUSTERED INDEX ix_itm ON #itm(code);

-- ===== 2. THE SHEET. Product code and customer code, both Sage, one row per product =====
SELECT b.part        AS [Product code],
       x.SAGE_CODE   AS [Customer code]
FROM   #best b
JOIN   #itm i ON i.code = b.part
JOIN   migration.XREF_SAGE_BPC x ON x.ACCESS_CODE = b.access_customer
ORDER  BY b.part;

-- ===== 3. The same with the working behind it, for the second tab =====
SELECT b.part                                      AS [Product code],
       x.SAGE_CODE                                 AS [Customer code],
       b.access_customer                           AS [Access customer code],
       LEFT(LTRIM(RTRIM(a.CUNAME)), 40)            AS [Customer name],
       b.order_lines                               AS [Order lines],
       b.qty_ordered                               AS [Quantity ordered],
       CONVERT(varchar(10), b.last_ordered, 23)    AS [Last ordered],
       b.customers_ever_used                       AS [Customers ever used]
FROM   #best b
JOIN   #itm i ON i.code = b.part
JOIN   migration.XREF_SAGE_BPC x ON x.ACCESS_CODE = b.access_customer
LEFT JOIN dbo.SL_ACCOUNTS a
       ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = b.access_customer
ORDER  BY b.part;

-- ===== 4. How much of the product list this covers =====
SELECT (SELECT COUNT(*) FROM #itm)                                  AS products_in_the_item_load,
       (SELECT COUNT(*) FROM #best b JOIN #itm i ON i.code = b.part
          JOIN migration.XREF_SAGE_BPC x ON x.ACCESS_CODE = b.access_customer)
                                                                    AS products_with_a_customer,
       (SELECT COUNT(*) FROM #best b JOIN #itm i ON i.code = b.part
          JOIN migration.XREF_SAGE_BPC x ON x.ACCESS_CODE = b.access_customer
         WHERE b.customers_ever_used > 1)                           AS sold_to_more_than_one,
       (SELECT COUNT(*) FROM #best b JOIN #itm i ON i.code = b.part
         WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPC x
                            WHERE x.ACCESS_CODE = b.access_customer))
                                                                    AS customer_has_no_sage_code,
       (SELECT COUNT(*) FROM #best b
         WHERE NOT EXISTS (SELECT 1 FROM #itm i WHERE i.code = b.part))
                                                                    AS product_not_in_the_item_load;

-- ===== 5. The customers that cost us rows, biggest first =====
SELECT b.access_customer AS access_code,
       LEFT(LTRIM(RTRIM(a.CUNAME)), 40) AS name,
       COUNT(*) AS products_affected
FROM   #best b
JOIN   #itm i ON i.code = b.part
LEFT JOIN dbo.SL_ACCOUNTS a
       ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = b.access_customer
WHERE  NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPC x
                    WHERE x.ACCESS_CODE = b.access_customer)
GROUP BY b.access_customer, LEFT(LTRIM(RTRIM(a.CUNAME)), 40)
ORDER BY products_affected DESC;

-- ===== 6. A sanity check worth having: does the code prefix agree with the customer? =====
-- SDI product codes often carry the customer - TES-, MS-, BOT-. Where the derived
-- customer disagrees with the prefix, it is worth a look before anyone relies on it.
SELECT TOP 20 LEFT(b.part, 3) AS code_prefix,
       LEFT(LTRIM(RTRIM(a.CUNAME)), 30) AS derived_customer,
       COUNT(*) AS products
FROM   #best b
JOIN   #itm i ON i.code = b.part
LEFT JOIN dbo.SL_ACCOUNTS a
       ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = b.access_customer
WHERE  LEFT(b.part, 3) IN ('TES', 'MS-', 'BOT', 'TIE', 'CTB', 'PER', 'VUE', 'MOT')
GROUP BY LEFT(b.part, 3), LEFT(LTRIM(RTRIM(a.CUNAME)), 30)
ORDER BY code_prefix, products DESC;
GO
