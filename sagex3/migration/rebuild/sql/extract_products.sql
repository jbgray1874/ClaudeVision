-- extract_products.sql  -  READ ONLY, changes nothing. Temporary tables in tempdb only.
--
-- Everything the product builder (products.py) needs, in one run:
--   ITEM    every product in migration.vw_ITM with its grade from vw_DQ_ITM - nothing filtered here
--   MASTER  codes Access holds in the part master or stock master that vw_ITM does not
--   USE     per Access code: stock on hand, open sales / purchase / works orders, last sale,
--           last purchase, last works order, do-not-use flag, Access material cost, lot cost,
--           last purchase price
--   BOM     every parent - component pair in vw_BOMP
--   RATE    Access's own exchange rate per currency, from the purchase ledger
--
-- Which products go into Sage is decided in products.py, on the runbook's rules (1a), and
-- every product left out is listed there with its reason. Nothing is dropped in this query.
--
-- Codes are the raw Access codes, trimmed: the code rule is applied once, in common.py.
-- Each table is read once, grouped into a small temporary table, then joined; there is no
-- cleansing expression in a join, so no index is lost. Expect a minute or two.
--
-- Results To File, tab delimited, into the run's extract folder as extract_products.txt.
-- Every grid starts with its label; the builder reads the grids by label.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ---- the product view and its grade ---------------------------------------------------
IF OBJECT_ID('tempdb..#itm') IS NOT NULL DROP TABLE #itm;
SELECT CAST(LTRIM(RTRIM(v.ITMREF)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       CAST(RTRIM(ISNULL(v.TCLCOD, '')) AS nvarchar(10))  AS TCLCOD,
       CAST(ISNULL(v.ITMDES1, '') AS nvarchar(60))        AS ITMDES1,
       CAST(ISNULL(v.ITMDES2, '') AS nvarchar(60))        AS ITMDES2,
       CAST(ISNULL(v.ITMDES3, '') AS nvarchar(60))        AS ITMDES3,
       CAST(ISNULL(v.STU, '') AS nvarchar(4))             AS STU,
       CAST(ISNULL(v.PUU, '') AS nvarchar(4))             AS PUU,
       v.PUUSTUCOE,
       CAST(ISNULL(v.SAU, '') AS nvarchar(4))             AS SAU,
       v.SAUSTUCOE,
       CAST(ISNULL(v.WEU, '') AS nvarchar(4))             AS WEU,
       ISNULL(v.ITMWEI, 0)                                AS ITMWEI,
       ISNULL(v.BASPRI, 0)                                AS BASPRI
INTO   #itm
FROM   migration.vw_ITM v
WHERE  LTRIM(RTRIM(ISNULL(v.ITMREF, ''))) <> '';
CREATE CLUSTERED INDEX ix_itm ON #itm(code);

IF OBJECT_ID('tempdb..#dq') IS NOT NULL DROP TABLE #dq;
SELECT CAST(LTRIM(RTRIM(d.ITMREF)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       CAST(MAX(d.DQ_STATUS) AS nvarchar(12))             AS DQ_STATUS
INTO   #dq
FROM   migration.vw_DQ_ITM d
WHERE  LTRIM(RTRIM(ISNULL(d.ITMREF, ''))) <> ''
GROUP BY LTRIM(RTRIM(d.ITMREF));
CREATE CLUSTERED INDEX ix_dq ON #dq(code);

-- ---- the masters ----------------------------------------------------------------------
IF OBJECT_ID('tempdb..#pma') IS NOT NULL DROP TABLE #pma;
SELECT CAST(LTRIM(RTRIM(PMA_PART_ONLY)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       MAX(CAST(PMA_DO_NOT_USE AS int))                   AS do_not_use,
       MAX(CAST(ISNULL(PMA_COST_MAT, 0) AS decimal(18, 5))) AS cost_mat,
       MAX(CAST(LTRIM(RTRIM(ISNULL(PMA_DESC_1, ''))) AS nvarchar(60))) AS desc1,
       MAX(CAST(LTRIM(RTRIM(ISNULL(PMA_DESC_3, ''))) AS nvarchar(60))) AS desc3,
       MAX(CAST(LTRIM(RTRIM(ISNULL(PMA_UOM, ''))) AS nvarchar(10)))    AS uom
INTO   #pma
FROM   dbo.ASC_PMA_TBL
WHERE  LTRIM(RTRIM(ISNULL(PMA_PART_ONLY, ''))) <> ''
GROUP BY LTRIM(RTRIM(PMA_PART_ONLY));
CREATE CLUSTERED INDEX ix_pma ON #pma(code);

IF OBJECT_ID('tempdb..#stk') IS NOT NULL DROP TABLE #stk;
SELECT CAST(LTRIM(RTRIM(STKCODE)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       MAX(CAST(LTRIM(RTRIM(ISNULL(STKNAME, ''))) AS nvarchar(60))) AS name,
       MAX(ISNULL(CAST(STK_DO_NOT_USE AS nvarchar(5)), ''))  AS do_not_use,
       MAX(ISNULL(CAST(STK_ARCHIVE AS nvarchar(5)), ''))     AS archive
INTO   #stk
FROM   dbo.STK_STOCK
WHERE  LTRIM(RTRIM(ISNULL(STKCODE, ''))) <> ''
GROUP BY LTRIM(RTRIM(STKCODE));
CREATE CLUSTERED INDEX ix_stk ON #stk(code);

-- ---- activity, one pass per table ------------------------------------------------------
-- stock on hand, at full lot cost (material + labour + overhead + other, as the stock file)
IF OBJECT_ID('tempdb..#lot') IS NOT NULL DROP TABLE #lot;
SELECT CAST(LTRIM(RTRIM(LOT_PART_ONLY)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       CAST(SUM(LOT_PHYSICAL) AS decimal(18, 4))          AS qty,
       CAST(SUM(LOT_PHYSICAL * (ISNULL(LOT_COST_EACH, 0) + ISNULL(LOT_LAB_COST_EACH, 0)
              + ISNULL(LOT_OHD_COST_EA, 0) + ISNULL(LOT_OTHER_COST_EA, 0))) AS decimal(18, 2)) AS value
INTO   #lot
FROM   dbo.ASC_LOT_TBL
WHERE  LOT_PHYSICAL > 0 AND LTRIM(RTRIM(ISNULL(LOT_PART_ONLY, ''))) <> ''
GROUP BY LTRIM(RTRIM(LOT_PART_ONLY));
CREATE CLUSTERED INDEX ix_lot ON #lot(code);

-- sales: open lines on the vw_SOH_V2 rule, and the last order date of any line
IF OBJECT_ID('tempdb..#so') IS NOT NULL DROP TABLE #so;
SELECT CAST(LTRIM(RTRIM(COR_PART_ONLY)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       SUM(CASE WHEN COR_QTY_ORDERED - ISNULL(COR_QTY_DELIVERED, 0) > 0
                 AND ISNULL(COR_ORDER_STATUS, '') IN ('', 'B', 'H') THEN 1 ELSE 0 END) AS open_lines,
       MAX(COR_ORDER_DATE)                                AS last_date
INTO   #so
FROM   dbo.ASC_COR_TBL
WHERE  LTRIM(RTRIM(ISNULL(COR_PART_ONLY, ''))) <> ''
GROUP BY LTRIM(RTRIM(COR_PART_ONLY));
CREATE CLUSTERED INDEX ix_so ON #so(code);

-- purchases: open lines on the vw_POH_V2 rule, the last order date, and the last priced line
IF OBJECT_ID('tempdb..#pol') IS NOT NULL DROP TABLE #pol;
SELECT CAST(LTRIM(RTRIM(POR_PART_ONLY)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       POR_ORDER_DATE                                     AS order_date,
       CASE WHEN POR_QTY_ORDERED - ISNULL(POR_QTY_DELIVERED, 0) - ISNULL(POR_QTY_REJECTED, 0) > 0
            THEN 1 ELSE 0 END                             AS is_open,
       CAST(ISNULL(POR_FORN_PRICE, 0) AS decimal(18, 5))  AS price,
       CAST(LTRIM(RTRIM(ISNULL(POR_CURR_CODE, ''))) AS nvarchar(4)) AS currency
INTO   #pol
FROM   dbo.ASC_POR_TBL
WHERE  LTRIM(RTRIM(ISNULL(POR_PART_ONLY, ''))) <> '';

IF OBJECT_ID('tempdb..#po') IS NOT NULL DROP TABLE #po;
SELECT code, SUM(is_open) AS open_lines, MAX(order_date) AS last_date
INTO   #po FROM #pol GROUP BY code;
CREATE CLUSTERED INDEX ix_po ON #po(code);

IF OBJECT_ID('tempdb..#price') IS NOT NULL DROP TABLE #price;
SELECT code, price, currency, order_date
INTO   #price
FROM  (SELECT code, price, currency, order_date,
              ROW_NUMBER() OVER (PARTITION BY code ORDER BY order_date DESC, price DESC) AS rn
       FROM #pol WHERE price > 0) z
WHERE  rn = 1;
CREATE CLUSTERED INDEX ix_price ON #price(code);

-- works orders: open (status blank, as works_orders_extract.sql) and the last one raised
IF OBJECT_ID('tempdb..#wo') IS NOT NULL DROP TABLE #wo;
SELECT CAST(LTRIM(RTRIM(WOR_ITEM_ONLY)) AS nvarchar(60)) COLLATE DATABASE_DEFAULT AS code,
       SUM(CASE WHEN LTRIM(RTRIM(ISNULL(WOR_STATUS, ''))) = '' THEN 1 ELSE 0 END) AS open_orders,
       MAX(COALESCE(WOR_FIRST_DATE, WOR_CREATED_DATE, WOR_DATE_SCHED)) AS last_date
INTO   #wo
FROM   dbo.ASC_WOR_TBL
WHERE  LTRIM(RTRIM(ISNULL(WOR_ITEM_ONLY, ''))) <> ''
GROUP BY LTRIM(RTRIM(WOR_ITEM_ONLY));
CREATE CLUSTERED INDEX ix_wo ON #wo(code);

-- every code seen anywhere above
IF OBJECT_ID('tempdb..#all') IS NOT NULL DROP TABLE #all;
SELECT code INTO #all FROM #itm UNION SELECT code FROM #pma UNION SELECT code FROM #stk
UNION SELECT code FROM #lot UNION SELECT code FROM #so UNION SELECT code FROM #po UNION SELECT code FROM #wo;
CREATE CLUSTERED INDEX ix_all ON #all(code);

-- Tabs and line breaks in a description would split a row in the file, so the grids below
-- replace them with spaces.

-- ===== ITEM: every product in vw_ITM, with its grade ===================================
SELECT 'ITEM' AS grid, i.code, i.TCLCOD,
       REPLACE(REPLACE(REPLACE(i.ITMDES1, CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS ITMDES1,
       REPLACE(REPLACE(REPLACE(i.ITMDES2, CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS ITMDES2,
       REPLACE(REPLACE(REPLACE(i.ITMDES3, CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS ITMDES3,
       i.STU, i.PUU, i.PUUSTUCOE, i.SAU, i.SAUSTUCOE, i.WEU, i.ITMWEI, i.BASPRI,
       ISNULL(d.DQ_STATUS, '(not graded)') AS DQ_STATUS
FROM   #itm i
LEFT JOIN #dq d ON d.code = i.code
ORDER BY i.code;

-- ===== MASTER: codes in the part or stock master that vw_ITM does not hold =============
SELECT 'MASTER' AS grid, a.code,
       CASE WHEN p.code IS NULL THEN 0 ELSE 1 END AS in_part_master,
       CASE WHEN s.code IS NULL THEN 0 ELSE 1 END AS in_stock_master,
       REPLACE(REPLACE(REPLACE(ISNULL(s.name, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ')  AS stock_name,
       REPLACE(REPLACE(REPLACE(ISNULL(p.desc1, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS part_desc1,
       REPLACE(REPLACE(REPLACE(ISNULL(p.desc3, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS part_desc3,
       ISNULL(p.uom, '') AS uom,
       ISNULL(d.DQ_STATUS, '(not graded)') AS DQ_STATUS
FROM   #all a
LEFT JOIN #pma p ON p.code = a.code
LEFT JOIN #stk s ON s.code = a.code
LEFT JOIN #dq d ON d.code = a.code
WHERE  NOT EXISTS (SELECT 1 FROM #itm i WHERE i.code = a.code)
ORDER BY a.code;

-- ===== USE: what each code is doing in Access =========================================
SELECT 'USE' AS grid, a.code,
       ISNULL(l.qty, 0)                                   AS stock_qty,
       ISNULL(l.value, 0)                                 AS stock_value,
       ISNULL(so.open_lines, 0)                           AS open_so_lines,
       ISNULL(po.open_lines, 0)                           AS open_po_lines,
       ISNULL(wo.open_orders, 0)                          AS open_works_orders,
       ISNULL(CONVERT(char(8), so.last_date, 112), '')    AS last_sale,
       ISNULL(CONVERT(char(8), po.last_date, 112), '')    AS last_purchase,
       ISNULL(CONVERT(char(8), wo.last_date, 112), '')    AS last_works_order,
       ISNULL(p.do_not_use, 0)                            AS part_do_not_use,
       ISNULL(s.do_not_use, '')                           AS stock_do_not_use,
       ISNULL(s.archive, '')                              AS stock_archive,
       ISNULL(p.cost_mat, 0)                              AS access_material_cost,
       ISNULL(pr.price, 0)                                AS last_purchase_price,
       ISNULL(pr.currency, '')                            AS last_purchase_currency,
       ISNULL(CONVERT(char(8), pr.order_date, 112), '')   AS last_priced_purchase
FROM   #all a
LEFT JOIN #lot l    ON l.code = a.code
LEFT JOIN #so so    ON so.code = a.code
LEFT JOIN #po po    ON po.code = a.code
LEFT JOIN #wo wo    ON wo.code = a.code
LEFT JOIN #pma p    ON p.code = a.code
LEFT JOIN #stk s    ON s.code = a.code
LEFT JOIN #price pr ON pr.code = a.code
ORDER BY a.code;

-- ===== BOM: every parent - component pair ==============================================
SELECT DISTINCT 'BOM' AS grid,
       CAST(LTRIM(RTRIM(ITMREF)) AS nvarchar(60))    AS parent,
       CAST(LTRIM(RTRIM(CPNITMREF)) AS nvarchar(60)) AS component
FROM   migration.vw_BOMP
WHERE  LTRIM(RTRIM(ISNULL(ITMREF, ''))) <> '' AND LTRIM(RTRIM(ISNULL(CPNITMREF, ''))) <> '';

-- ===== RATE: Access's own rate per currency (GBP / currency on open purchase ledger items)
SELECT 'RATE' AS grid,
       LTRIM(RTRIM(PT_CURRENCYCODE))                                        AS currency,
       COUNT(*)                                                             AS items,
       CAST(AVG(ABS(PT_UNALLOCATED) / ABS(PT_CURR_UNAL)) AS decimal(18, 6)) AS avg_rate,
       CAST(MIN(ABS(PT_UNALLOCATED) / ABS(PT_CURR_UNAL)) AS decimal(18, 6)) AS min_rate,
       CAST(MAX(ABS(PT_UNALLOCATED) / ABS(PT_CURR_UNAL)) AS decimal(18, 6)) AS max_rate
FROM   dbo.PL_TRANSACTIONS
WHERE  PT_UNALLOCATED <> 0 AND ISNULL(PT_CURR_UNAL, 0) <> 0
  AND  LTRIM(RTRIM(ISNULL(PT_CURRENCYCODE, ''))) NOT IN ('', 'GBP')
GROUP BY LTRIM(RTRIM(PT_CURRENCYCODE));
GO
