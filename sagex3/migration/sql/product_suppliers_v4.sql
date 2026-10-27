-- product_suppliers_v4.sql  -  READ ONLY, changes nothing (temporary tables only, in tempdb)
--
-- product_suppliers_v3.sql with the 83 new supplier codes written in, so the products
-- bought from the suppliers that were missing from X3 come through, without changing any table.
-- (Motion Print Ready alone is the only supplier of 940 products.)
--
-- Three grids. Grid 2 is the list - export it with Results To File, tab delimited, and send it back.
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

IF OBJECT_ID('tempdb..#newsup') IS NOT NULL DROP TABLE #newsup;
CREATE TABLE #newsup (ACCESS_CODE varchar(20) COLLATE DATABASE_DEFAULT PRIMARY KEY, SAGE_CODE varchar(10) COLLATE DATABASE_DEFAULT);
INSERT INTO #newsup (ACCESS_CODE, SAGE_CODE) VALUES
    ('AVL01', 'ACT500'),
    ('ADP01', 'ADR500'),
    ('PAR07', 'ASH502'),
    ('AAL03', 'ASS500'),
    ('AGL01', 'ATE500'),
    ('AGL01PL', 'ATE501'),
    ('BAL01', 'BAL500'),
    ('BWL01', 'BIA500'),
    ('BCW01', 'BIC500'),
    ('BVC01', 'BUR500'),
    ('COT02', 'CAP500'),
    ('CHS01', 'CAS500'),
    ('CLM01', 'CLA501'),
    ('CLC01', 'CLC500'),
    ('CFL02', 'CON504'),
    ('CCC02', 'CRO501'),
    ('CSW01', 'CSW500'),
    ('DA001', 'DEB500'),
    ('DIE01', 'DIE500'),
    ('EMS01', 'EAS501'),
    ('ECO04', 'ECO500'),
    ('EMT01', 'ELE500'),
    ('ELM01', 'ELL500'),
    ('EMB01', 'EMI500'),
    ('EPL03', 'ENG500'),
    ('ERL03', 'EUR501'),
    ('FFL04', 'FOR501'),
    ('FFL01', 'FOR502'),
    ('FML01', 'FOR503'),
    ('FRE04', 'FRE501'),
    ('GJW01', 'GJW500'),
    ('GIL01', 'GLO500'),
    ('GRG01', 'GRG500'),
    ('HRC01', 'HOY500'),
    ('HUN04', 'HUN500'),
    ('IMZ01', 'IMA500'),
    ('JWR01', 'JAC500'),
    ('JCE01', 'JCE500'),
    ('JLC01', 'JLC500'),
    ('JLY01', 'JLY500'),
    ('JRP01', 'JRP500'),
    ('LTL03', 'LIU500'),
    ('LKW03', 'LKW500'),
    ('LKW02', 'LKW501'),
    ('MCH01', 'MAS501'),
    ('MXM01', 'MAT501'),
    ('MLS02', 'MID500'),
    ('MNL01', 'MIK501'),
    ('MCO02', 'MIL501'),
    ('MPR01', 'MOT501'),
    ('MGT01', 'MYG500'),
    ('NTL02', 'NIN500'),
    ('NTL02PL', 'NIN501'),
    ('OCT01', 'OCT501'),
    ('OSI01', 'ONE500'),
    ('TPC01', 'PAC501'),
    ('PGB02', 'PAR501'),
    ('PRL04', 'PER501'),
    ('PCD03PL', 'PIO500'),
    ('PDC02', 'PIO501'),
    ('QRD01', 'QRD500'),
    ('TRG01', 'REC501'),
    ('RCL02', 'RIV501'),
    ('SMI03', 'ROB500'),
    ('AWL03', 'ROB501'),
    ('SRD01', 'SLI501'),
    ('SLM01', 'SLM500'),
    ('SDC01', 'STA501'),
    ('SJS01', 'STE502'),
    ('TIL01', 'STU501'),
    ('TEC04', 'TEC501'),
    ('TFS02', 'TRU501'),
    ('TTS01', 'TTS500'),
    ('UKF01', 'UKF500'),
    ('TUW01', 'UPH501'),
    ('WRC03', 'WEA500'),
    ('WIL21', 'WHI501'),
    ('WAP02', 'WIL501'),
    ('XYS01', 'XIA501'),
    ('XMD01', 'XIA502'),
    ('XYS01PL', 'XIA503'),
    ('JZH01', 'ZHE500'),
    ('ZPK01', 'ZPK500');

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
       COALESCE(x.SAGE_CODE, ns.SAGE_CODE) COLLATE DATABASE_DEFAULT AS sage_supplier
INTO   #pair
FROM   agg a
JOIN   latest t ON t.product = a.product AND t.access_supplier = a.access_supplier AND t.rn = 1
LEFT JOIN migration.XREF_SAGE_BPS x ON x.ACCESS_CODE = a.access_supplier
LEFT JOIN #newsup ns ON ns.ACCESS_CODE = a.access_supplier;

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
       ISNULL(n.SAGE_NAME, LTRIM(RTRIM(ISNULL(s.SUNAME, '')))) AS supplier_name,
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
LEFT JOIN dbo.PL_ACCOUNTS s ON LTRIM(RTRIM(s.SUCODE)) COLLATE DATABASE_DEFAULT = p.access_supplier
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
