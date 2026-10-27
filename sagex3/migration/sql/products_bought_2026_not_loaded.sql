-- products_bought_2026_not_loaded.sql  -  READ ONLY, changes nothing (temporary tables only, in tempdb)
--
-- 106 products bought in 2026 from the suppliers that were missing from X3, that are not in
-- the product file (ZSDIITM). For each: its grade in migration.vw_DQ_ITM (the rule that picked the
-- product file), and whether it is live - open PO lines, open sales order lines, stock.
-- One grid. Results To File, tab delimited, and send it back.
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

WITH dq AS (
    SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(ITMREF))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           MAX(LTRIM(RTRIM(ITMREF))) AS access_code, MAX(DQ_STATUS) AS dq_status,
           MAX(LEFT(LTRIM(RTRIM(ISNULL(ITMDES1, ''))), 40)) AS description
    FROM migration.vw_DQ_ITM
    GROUP BY UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(ITMREF))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
), po AS (
    SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(POR_PART_ONLY))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           SUM(CASE WHEN ISNULL(POR_QTY_ORDERED, 0) - ISNULL(POR_QTY_DELIVERED, 0) - ISNULL(POR_QTY_REJECTED, 0) > 0
                    THEN 1 ELSE 0 END) AS open_po_lines,
           MIN(POR_ORDER_DATE) AS first_bought, MAX(POR_ORDER_DATE) AS last_bought
    FROM dbo.ASC_POR_TBL
    GROUP BY UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(POR_PART_ONLY))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
), so AS (
    SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(COR_PART_ONLY))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           SUM(CASE WHEN ISNULL(COR_QTY_ORDERED, 0) > ISNULL(COR_QTY_DELIVERED, 0)
                     AND ISNULL(COR_ORDER_STATUS, '') IN ('', 'B', 'H') THEN 1 ELSE 0 END) AS open_so_lines,
           MAX(COR_ORDER_DATE) AS last_sold
    FROM dbo.ASC_COR_TBL
    GROUP BY UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(COR_PART_ONLY))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
), stock AS (
    SELECT CAST(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(ITMREF))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-')) AS varchar(60)) COLLATE DATABASE_DEFAULT AS code,
           CAST(SUM(QTYSTU) AS decimal(18, 2)) AS stock_qty
    FROM migration.vw_SMR_V2
    GROUP BY UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(ITMREF))), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
)
SELECT p.code,
       ISNULL(d.access_code, '')                     AS access_code,
       ISNULL(d.dq_status, 'NOT IN vw_DQ_ITM')        AS dq_status,
       ISNULL(d.description, '')                     AS description,
       ISNULL(po.open_po_lines, 0)                   AS open_po_lines,
       ISNULL(so.open_so_lines, 0)                   AS open_so_lines,
       ISNULL(st.stock_qty, 0)                       AS stock_qty,
       CONVERT(varchar(10), po.first_bought, 23)     AS first_bought,
       CONVERT(varchar(10), po.last_bought, 23)      AS last_bought,
       CONVERT(varchar(10), so.last_sold, 23)        AS last_sold
FROM #p p
LEFT JOIN dq d     ON d.code  = p.code
LEFT JOIN po       ON po.code = p.code
LEFT JOIN so       ON so.code = p.code
LEFT JOIN stock st ON st.code = p.code
ORDER BY ISNULL(po.open_po_lines, 0) + ISNULL(so.open_so_lines, 0) DESC, p.code;
GO
