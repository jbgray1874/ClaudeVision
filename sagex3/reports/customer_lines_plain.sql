-- customer_lines_plain.sql  -  READ ONLY (Access SupplyChain, SDILive). Changes nothing. REP-24 (SCRUM-336).
-- One customer's product lines: this year to date, with last year beside it. Run in SSMS (F5), Results to Grid.
-- Grid 1 = one row per part (by this year's value), grid 2 = every order line.
-- Right-click each grid > Copy with Headers > paste into its own Excel tab. First run 22 Nov 2026; re-run 31 Dec 2026.
-- Placeholders in git: set @name_like (the customer's sales-ledger name, with %) and @part_like (their part-code
-- prefix, e.g. 'ABC-%') in SSMS only. Customer names and part-code prefixes never go in git.
-- Known limits (22 Nov run): labour and scrap are not booked on Access works orders, so cost = materials only and the
-- margin is a material margin; bought-in parts show no cost (their cost is on purchase orders).
USE SDILive;
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

DECLARE @name_like varchar(60) = '%XXXXX%';   -- <- the customer's name as in the sales ledger
DECLARE @part_like varchar(30) = 'XXXXX-%';   -- <- their part-code prefix
DECLARE @y0 date = '2026-01-01', @p0 date = '2025-01-01';   -- this year from, last year from

-- 1. ONE ROW PER PART
WITH acc AS (
    SELECT LTRIM(RTRIM(CUCODE)) COLLATE DATABASE_DEFAULT AS code FROM dbo.SL_ACCOUNTS WHERE CUNAME LIKE @name_like),
l AS (
    SELECT LTRIM(RTRIM(c.COR_PART_ONLY)) COLLATE DATABASE_DEFAULT AS part,
           CAST(c.COR_ORDER_DATE AS date) AS d,
           LTRIM(RTRIM(c.COR_OUR_NUMBER)) AS order_no,
           CAST(c.COR_QTY_ORDERED AS decimal(18, 3)) AS qty,
           CAST(ISNULL(c.COR_QTY_DELIVERED, 0) AS decimal(18, 3)) AS dq,
           CAST(COALESCE(CASE WHEN ISNULL(c.COR_DISC_PRICE, 0) <> 0 THEN c.COR_DISC_PRICE / NULLIF(CAST(c.COR_DISC_PRICE_PER AS decimal(18, 6)), 0) END,
                         CASE WHEN ISNULL(c.COR_ORIG_PRICE, 0) <> 0 THEN c.COR_ORIG_PRICE / NULLIF(CAST(c.COR_ORIG_PRICE_PER AS decimal(18, 6)), 0) END,
                         0) AS decimal(18, 5)) AS price
    FROM dbo.ASC_COR_TBL c
    WHERE c.COR_ORDER_DATE >= @p0
      AND LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> ''
      AND (LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT IN (SELECT code FROM acc)
           OR LTRIM(RTRIM(c.COR_PART_ONLY)) LIKE @part_like)),
s AS (
    SELECT part,
           COUNT(DISTINCT CASE WHEN d >= @y0 THEN order_no END) AS orders_2026,
           SUM(CASE WHEN d >= @y0 THEN qty ELSE 0 END)           AS qty_2026,
           SUM(CASE WHEN d >= @y0 THEN dq ELSE 0 END)            AS delivered_2026,
           SUM(CASE WHEN d >= @y0 THEN qty * price ELSE 0 END)   AS value_2026,
           MIN(CASE WHEN d >= @y0 AND price > 0 THEN price END)  AS min_price_2026,
           MAX(CASE WHEN d >= @y0 THEN price END)                AS max_price_2026,
           SUM(CASE WHEN d < @y0 THEN qty ELSE 0 END)            AS qty_2025,
           SUM(CASE WHEN d < @y0 THEN qty * price ELSE 0 END)    AS value_2025,
           MAX(d)                                                AS last_ordered
    FROM l GROUP BY part),
w AS (
    SELECT LTRIM(RTRIM(WOR_ITEM_ONLY)) COLLATE DATABASE_DEFAULT AS part,
           COUNT(*)                                                     AS wos_2026,
           SUM(CAST(ISNULL(WOR_GOOD_QTY, 0) AS decimal(18, 3)))         AS made_2026,
           SUM(CAST(ISNULL(WOR_REJECTED_QTY, 0) + ISNULL(WOR_SCRAP_QTY, 0) AS decimal(18, 3))) AS rej_scrap_2026,
           AVG(CAST(ISNULL(WOR_GOOD_QTY, 0) AS decimal(18, 3)))         AS avg_batch,
           MIN(CAST(ISNULL(WOR_GOOD_QTY, 0) AS decimal(18, 3)))         AS min_batch,
           MAX(CAST(ISNULL(WOR_GOOD_QTY, 0) AS decimal(18, 3)))         AS max_batch,
           SUM(CAST(ISNULL(WOR_BOOKED_MAT_COST, 0) AS decimal(18, 2)))  AS mat,
           SUM(CAST(ISNULL(WOR_BOOKED_LAB_COST, 0) AS decimal(18, 2)))  AS lab,
           SUM(CAST(ISNULL(WOR_BOOKED_SC_COST, 0) AS decimal(18, 2)))   AS sc
    FROM dbo.ASC_WOR_TBL
    WHERE WOR_STATUS = 'C' AND COALESCE(WOR_DONE_DATE, WOR_DATE_SCHED) >= @y0
      AND LTRIM(RTRIM(WOR_ITEM_ONLY)) COLLATE DATABASE_DEFAULT IN (SELECT part FROM s)
    GROUP BY LTRIM(RTRIM(WOR_ITEM_ONLY))),
x AS (
    SELECT s.*, w.wos_2026, w.made_2026, w.rej_scrap_2026, w.avg_batch, w.min_batch, w.max_batch,
           s.value_2026 / NULLIF(s.qty_2026, 0)                         AS avg_price_2026,
           w.mat / NULLIF(w.made_2026, 0)                               AS material_per_unit,
           w.lab / NULLIF(w.made_2026, 0)                               AS labour_per_unit,
           (w.mat + w.lab + w.sc) / NULLIF(w.made_2026, 0)              AS wo_cost_per_unit,
           CAST(pm.cost / NULLIF(pm.cost_per, 0) AS decimal(18, 5))     AS access_std_cost,
           w.rej_scrap_2026 / NULLIF(w.made_2026 + w.rej_scrap_2026, 0) AS scrap_pct,
           ISNULL(pm.descr, '')                                         AS description
    FROM s
    LEFT JOIN w ON w.part = s.part
    OUTER APPLY (SELECT TOP 1 LTRIM(RTRIM(PMA_DESC_1)) AS descr, CAST(ISNULL(PMA_COST, 0) AS decimal(18, 5)) AS cost,
                        CAST(NULLIF(PMA_COST_PER, 0) AS decimal(18, 5)) AS cost_per
                 FROM dbo.ASC_PMA_TBL WHERE LTRIM(RTRIM(PMA_PART_ONLY)) COLLATE DATABASE_DEFAULT = s.part) pm),
y AS (
    SELECT x.*, COALESCE(NULLIF(wo_cost_per_unit, 0), NULLIF(access_std_cost, 0)) AS cost_used,
           CASE WHEN NULLIF(wo_cost_per_unit, 0) IS NOT NULL THEN 'works orders 2026'
                WHEN NULLIF(access_std_cost, 0) IS NOT NULL THEN 'Access standard cost' ELSE 'no cost found' END AS cost_basis
    FROM x),
z AS (
    SELECT y.*, avg_price_2026 - cost_used AS margin_per_unit,
           (avg_price_2026 - cost_used) / NULLIF(avg_price_2026, 0) AS margin_pct
    FROM y)
SELECT part, description, orders_2026, qty_2026, delivered_2026,
       CAST(value_2026 AS decimal(18, 2)) AS value_2026, CAST(avg_price_2026 AS decimal(18, 4)) AS avg_price_2026,
       min_price_2026, max_price_2026, qty_2025, CAST(value_2025 AS decimal(18, 2)) AS value_2025, last_ordered,
       wos_2026, made_2026, rej_scrap_2026, CAST(scrap_pct AS decimal(9, 4)) AS scrap_pct,
       CAST(avg_batch AS decimal(18, 1)) AS avg_batch, min_batch, max_batch,
       CAST(material_per_unit AS decimal(18, 4)) AS material_per_unit, CAST(labour_per_unit AS decimal(18, 4)) AS labour_per_unit,
       CAST(cost_used AS decimal(18, 4)) AS cost_per_unit, cost_basis, access_std_cost,
       CAST(margin_per_unit AS decimal(18, 4)) AS margin_per_unit, CAST(margin_pct AS decimal(9, 4)) AS margin_pct,
       CAST(margin_per_unit * qty_2026 AS decimal(18, 2)) AS margin_2026,
       CONCAT(CASE WHEN margin_pct < 0 THEN 'LOSS; ' WHEN margin_pct < 0.25 THEN 'Margin under 25%; ' END,
              CASE WHEN scrap_pct >= 0.03 THEN 'Scrap/rejects 3%+; ' END,
              CASE WHEN max_price_2026 > min_price_2026 * 1.05 THEN 'Price varies; ' END,
              CASE WHEN max_batch >= 3 * NULLIF(min_batch, 0) THEN 'Batch sizes vary 3x+; ' END,
              CASE WHEN cost_used IS NULL THEN 'No cost found; ' END) AS flags
FROM z
ORDER BY value_2026 DESC, part;

-- 2. EVERY ORDER LINE (2025 and 2026)
SELECT LTRIM(RTRIM(c.COR_PART_ONLY)) AS part, CAST(c.COR_ORDER_DATE AS date) AS order_date,
       LTRIM(RTRIM(c.COR_OUR_NUMBER)) AS order_no, c.COR_LINE_NUM AS line,
       LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) AS account, LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_ORDER, ''))) AS customer_po,
       CAST(c.COR_QTY_ORDERED AS decimal(18, 3)) AS qty_ordered, CAST(ISNULL(c.COR_QTY_DELIVERED, 0) AS decimal(18, 3)) AS qty_delivered,
       CAST(COALESCE(CASE WHEN ISNULL(c.COR_DISC_PRICE, 0) <> 0 THEN c.COR_DISC_PRICE / NULLIF(CAST(c.COR_DISC_PRICE_PER AS decimal(18, 6)), 0) END,
                     CASE WHEN ISNULL(c.COR_ORIG_PRICE, 0) <> 0 THEN c.COR_ORIG_PRICE / NULLIF(CAST(c.COR_ORIG_PRICE_PER AS decimal(18, 6)), 0) END,
                     0) AS decimal(18, 5)) AS unit_price,
       CAST(c.COR_CUSTOMER_DUE AS date) AS customer_due, LTRIM(RTRIM(ISNULL(c.COR_ORDER_STATUS, ''))) AS status
FROM dbo.ASC_COR_TBL c
WHERE c.COR_ORDER_DATE >= @p0
  AND LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> ''
  AND (LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT IN
           (SELECT LTRIM(RTRIM(CUCODE)) COLLATE DATABASE_DEFAULT FROM dbo.SL_ACCOUNTS WHERE CUNAME LIKE @name_like)
       OR LTRIM(RTRIM(c.COR_PART_ONLY)) LIKE @part_like)
ORDER BY part, order_date, order_no, line;
