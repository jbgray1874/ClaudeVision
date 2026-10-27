-- products_bought_2026_not_loaded.sql  -  READ ONLY, changes nothing (temporary tables only, in tempdb)
--
-- The 106 products bought in 2026 from the suppliers that were missing from X3, that are not in the
-- product file (ZSDIITM): their grade in migration.vw_DQ_ITM, and whether they are live (open PO
-- lines, open sales order lines, stock).
--
-- Built to be quick: one pass over the purchase order lines finds the 106 products and their
-- Access codes; every other lookup is then by those codes only. Nothing is totalled for products
-- outside the 106. One grid. Results To File, tab delimited, and send it back.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#p') IS NOT NULL DROP TABLE #p;
CREATE TABLE #p (code varchar(60) COLLATE DATABASE_DEFAULT PRIMARY KEY);
INSERT INTO #p (code) VALUES
    ('101700'), ('11807-02-GA2'), ('11807-03-GA'), ('11807-06-GA'), ('11807-07-GA'), ('11807-07-GA6'), ('11807-07-GA8'), ('11807-08-01A'),
    ('11807-08-02A'), ('11807-08-03A'), ('11807-14-GA'), ('11807-15-GA'), ('11807-16-GA'), ('11807-17-GAPART'), ('11807-18-GA'), ('11807-21-GA'),
    ('11807-22-GA'), ('12555-02-GACH'), ('513100'), ('549400'), ('641100'), ('AD02PORTNMC'), ('BE2025XOS'), ('BOT-12608-GAOS'),
    ('BOT-CABKEYLOCK'), ('BOT-CABRUNNER'), ('CARTON2023'), ('CASTOR0346654'), ('DELIVERY-NOVAT'), ('INSTALLTION'), ('L01-261'), ('L42-250'),
    ('L46-200'), ('L46-210'), ('L48-997'), ('LCL-INSTALL'), ('MISCPROTOTYPE'), ('NONSTOCKMISC'), ('PACK104'), ('PACK111'),
    ('PACK204'), ('PACK224'), ('PACK41'), ('PACK51'), ('PACK7'), ('PACK93'), ('PALLET77'), ('PRINT'),
    ('PRINT000010'), ('PRINT000011'), ('PRINT000012'), ('PRINT000013'), ('PRINT000014'), ('PRINT00006'), ('PRINT00007'), ('PRINT00008'),
    ('PRINT00009'), ('PRINT000100'), ('PRINT000106'), ('PRINT000107'), ('PRINT000108'), ('PRINT000110'), ('PRINT000111'), ('PRINT0001129'),
    ('PRINT0001130'), ('PRINT0001131'), ('PRINT0001145'), ('PRINT0001146'), ('PRINT0001147'), ('PRINT0001148'), ('PRINT0001149'), ('PRINT000120'),
    ('PRINT000139'), ('PRINT000142'), ('PRINT000194'), ('PRINT000196'), ('PRINT000203'), ('PRINT000204'), ('PRINT000205'), ('PRINT000206'),
    ('PRINT000207'), ('PRINT00137'), ('PRINT00138'), ('PRINT00139'), ('PRINT00142'), ('PRINT00143'), ('PRINT00149'), ('PRINT02'),
    ('PRINT0208'), ('PRINT0288'), ('PRINT0289'), ('PRINT0306'), ('PRINT0389'), ('PRINT054'), ('PRINT055'), ('PRINT1122'),
    ('PRINT11784-05A'), ('PRINT11784-05B'), ('PRINT11784-06-01'), ('PRINT12345'), ('PRINT127'), ('PROTOPRINT'), ('TESCO-PROTO'), ('TESTRANSPORT'),
    ('TOOLINGCOST'), ('Y86-266');

-- 1. The purchase order lines for the 106 (one pass over ASC_POR_TBL, 2026 orders and earlier)
IF OBJECT_ID('tempdb..#po') IS NOT NULL DROP TABLE #po;
SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(POR_PART_ONLY)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
       CAST(LTRIM(RTRIM(POR_PART_ONLY)) AS varchar(60)) COLLATE DATABASE_DEFAULT AS access_code,
       POR_ORDER_DATE AS order_date,
       CASE WHEN ISNULL(POR_QTY_ORDERED, 0) - ISNULL(POR_QTY_DELIVERED, 0) - ISNULL(POR_QTY_REJECTED, 0) > 0
            THEN 1 ELSE 0 END AS is_open
INTO   #po
FROM   dbo.ASC_POR_TBL
WHERE  UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(POR_PART_ONLY)), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) COLLATE DATABASE_DEFAULT IN (SELECT code FROM #p);

-- 2. Their Access codes as spelled in Access (a few differ from the cleaned code)
IF OBJECT_ID('tempdb..#raw') IS NOT NULL DROP TABLE #raw;
SELECT DISTINCT code, access_code INTO #raw FROM #po;

-- 3. Open sales order lines for those codes only
IF OBJECT_ID('tempdb..#so') IS NOT NULL DROP TABLE #so;
SELECT r.code,
       SUM(CASE WHEN ISNULL(c.COR_QTY_ORDERED, 0) > ISNULL(c.COR_QTY_DELIVERED, 0)
                 AND ISNULL(c.COR_ORDER_STATUS, '') IN ('', 'B', 'H') THEN 1 ELSE 0 END) AS open_so_lines,
       MAX(c.COR_ORDER_DATE) AS last_sold
INTO   #so
FROM   dbo.ASC_COR_TBL c
JOIN   #raw r ON r.access_code = c.COR_PART_ONLY COLLATE DATABASE_DEFAULT
GROUP BY r.code;

-- 4. Grade, from the product rule, for those codes only
IF OBJECT_ID('tempdb..#dq') IS NOT NULL DROP TABLE #dq;
SELECT r.code, MAX(d.DQ_STATUS) AS dq_status, MAX(LEFT(LTRIM(RTRIM(ISNULL(d.ITMDES1, ''))), 40)) AS description
INTO   #dq
FROM   migration.vw_DQ_ITM d
JOIN   #raw r ON r.access_code = d.ITMREF COLLATE DATABASE_DEFAULT
GROUP BY r.code;

-- 5. The grid
SELECT p.code,
       ISNULL((SELECT MAX(access_code) FROM #raw r WHERE r.code = p.code), '') AS access_code,
       ISNULL(d.dq_status, 'NOT IN vw_DQ_ITM')                                AS dq_status,
       ISNULL(d.description, '')                                              AS description,
       ISNULL(po.open_po_lines, 0)                                            AS open_po_lines,
       ISNULL(so.open_so_lines, 0)                                            AS open_so_lines,
       CONVERT(varchar(10), po.first_bought, 23)                              AS first_bought,
       CONVERT(varchar(10), po.last_bought, 23)                               AS last_bought,
       CONVERT(varchar(10), so.last_sold, 23)                                 AS last_sold
FROM #p p
LEFT JOIN (SELECT code, SUM(is_open) AS open_po_lines, MIN(order_date) AS first_bought,
                  MAX(order_date) AS last_bought
           FROM #po GROUP BY code) po ON po.code = p.code
LEFT JOIN #so so ON so.code = p.code
LEFT JOIN #dq d  ON d.code  = p.code
ORDER BY ISNULL(po.open_po_lines, 0) + ISNULL(so.open_so_lines, 0) DESC, p.code;
GO
