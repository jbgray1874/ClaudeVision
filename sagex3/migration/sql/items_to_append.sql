-- items_to_append.sql  -  READ ONLY, changes nothing
--
-- 182 products pass the item load's own rule (GOOD or INCOMPLETE) and are not in it.
-- 137 of those are in active use - on an open sales order, on an open purchase order,
-- or holding stock. This produces those 137 as rows in the ZSDIITM load format, ready
-- to append to the file.
--
-- Grid 2 gives them as a single semicolon-delimited line each, in the same 18-field
-- shape as ZSDIITM_Cleansing.txt, so they can be pasted straight onto the end of it.
-- Save that grid with Results To File and the result is the append.
--
-- The item code is cleansed the same way as the rest of the file: uppercase, no
-- spaces, no ampersands, no brackets, full stops to hyphens.
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

IF OBJECT_ID('tempdb..#inuse') IS NOT NULL DROP TABLE #inuse;
SELECT code, MAX(so) AS on_sales_order, MAX(po) AS on_purchase_order,
       MAX(st) AS in_stock, SUM(val) AS stock_value
INTO #inuse
FROM (
    SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           1 AS so, 0 AS po, 0 AS st, CAST(0 AS decimal(18,2)) AS val FROM migration.vw_SOH_V2
    UNION ALL SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT, 0, 1, 0, 0
           FROM migration.vw_POH_V2
    UNION ALL SELECT CAST(ITMREF AS varchar(60)) COLLATE DATABASE_DEFAULT, 0, 0, 1, REF_LOT_VALUE
           FROM migration.vw_SMR_V2
) z GROUP BY code;
CREATE CLUSTERED INDEX ix_u ON #inuse(code);

IF OBJECT_ID('tempdb..#add') IS NOT NULL DROP TABLE #add;
SELECT CAST(RTRIM(v.TCLCOD) AS varchar(10)) COLLATE DATABASE_DEFAULT            AS TCLCOD,
       CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           LTRIM(RTRIM(v.ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
           AS varchar(60)) COLLATE DATABASE_DEFAULT                              AS ITMREF,
       CAST(LTRIM(RTRIM(v.ITMREF)) AS varchar(60)) COLLATE DATABASE_DEFAULT      AS ACCESS_CODE,
       CAST(ISNULL(v.ITMDES1, '') AS varchar(30)) COLLATE DATABASE_DEFAULT       AS ITMDES1,
       CAST(ISNULL(v.ITMDES2, '') AS varchar(30)) COLLATE DATABASE_DEFAULT       AS ITMDES2,
       CAST(ISNULL(v.ITMDES3, '') AS varchar(30)) COLLATE DATABASE_DEFAULT       AS ITMDES3,
       CAST(v.STU AS varchar(4))  COLLATE DATABASE_DEFAULT                       AS STU,
       CAST(v.PUU AS varchar(4))  COLLATE DATABASE_DEFAULT                       AS PUU,
       v.PUUSTUCOE,
       CAST(v.SAU AS varchar(4))  COLLATE DATABASE_DEFAULT                       AS SAU,
       v.SAUSTUCOE,
       CAST(v.WEU AS varchar(4))  COLLATE DATABASE_DEFAULT                       AS WEU,
       ISNULL(v.ITMWEI, 0) AS ITMWEI, ISNULL(v.BASPRI, 0) AS BASPRI,
       CAST(d.DQ_STATUS AS varchar(12)) COLLATE DATABASE_DEFAULT                 AS DQ_STATUS,
       u.on_sales_order, u.on_purchase_order, u.in_stock,
       CAST(u.stock_value AS decimal(18, 2)) AS stock_value
INTO   #add
FROM   migration.vw_ITM v
JOIN   migration.vw_DQ_ITM d
       ON LTRIM(RTRIM(d.ITMREF)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(v.ITMREF)) COLLATE DATABASE_DEFAULT
JOIN   #inuse u
       ON u.code = UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
              LTRIM(RTRIM(v.ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) COLLATE DATABASE_DEFAULT
LEFT JOIN #itm i
       ON i.code = UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
              LTRIM(RTRIM(v.ITMREF)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) COLLATE DATABASE_DEFAULT
WHERE  i.code IS NULL
  AND  d.DQ_STATUS IN ('GOOD', 'INCOMPLETE');

-- ===== 1. What we are adding =====
SELECT DQ_STATUS,
       COUNT(*) AS products,
       SUM(on_sales_order) AS on_an_open_sales_order,
       SUM(on_purchase_order) AS on_an_open_purchase_order,
       SUM(in_stock) AS holding_stock,
       CAST(SUM(stock_value) AS decimal(18, 2)) AS stock_value
FROM #add GROUP BY DQ_STATUS
UNION ALL
SELECT 'TOTAL', COUNT(*), SUM(on_sales_order), SUM(on_purchase_order),
       SUM(in_stock), CAST(SUM(stock_value) AS decimal(18, 2)) FROM #add;

-- ===== 2. The rows themselves, ready to append to ZSDIITM =====
-- 18 fields, semicolon delimited, exactly as the existing file. Save with
-- Results To File, check it, and paste onto the end.
SELECT CONCAT(RTRIM(a.TCLCOD), ';', a.ITMREF, ';',
              REPLACE(RTRIM(a.ITMDES1), ';', ' '), ';',
              REPLACE(RTRIM(a.ITMDES2), ';', ' '), ';',
              REPLACE(RTRIM(a.ITMDES3), ';', ' '), ';',
              RTRIM(a.STU), ';', RTRIM(a.PUU), ';', a.PUUSTUCOE, ';',
              RTRIM(a.SAU), ';', a.SAUSTUCOE, ';', RTRIM(a.WEU), ';',
              CAST(a.ITMWEI AS decimal(18, 5)), ';',
              CAST(a.BASPRI AS decimal(18, 5)), ';;;;;') AS load_line
FROM #add a
ORDER BY a.ITMREF;

-- ===== 3. The same as columns, for a look before it goes anywhere =====
SELECT ACCESS_CODE, ITMREF AS sage_code, TCLCOD, DQ_STATUS,
       ITMDES1, ITMDES3, BASPRI,
       on_sales_order, on_purchase_order, in_stock, stock_value
FROM #add
ORDER BY DQ_STATUS, ITMREF;

-- ===== 4. Anything that would collide with a code already in the file =====
-- Two different Access codes can cleanse onto one Sage code. Appending blind would
-- let one overwrite the other, so this has to be empty before anything is appended.
SELECT a.ITMREF AS sage_code, COUNT(*) AS products_sharing_it,
       MAX(a.ACCESS_CODE) AS one_of_them
FROM #add a GROUP BY a.ITMREF HAVING COUNT(*) > 1;
GO
