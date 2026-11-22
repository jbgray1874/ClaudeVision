-- customer_year_end.sql  -  READ ONLY (Access SupplyChain, SDILive). Changes nothing. Written 22 Nov 2026.
-- A year-end record of every product line one customer buys, before the move to Sage X3, plus the works-order
-- data to review quantities, costs and margins (first asked for by the account director, 22 Nov).
--
-- Set the two values below. The committed copy keeps placeholders: customer names, codes and part-code prefixes
-- stay out of git.
--   @name_like  the customer's name as in the sales ledger, with % around it - every account whose name matches
--   @part_like  the customer's own part-code prefix (e.g. 'ABC-%'), so their parts ordered through other accounts
--               are found too; '' = accounts only
-- Period: this calendar year to today, and the whole of last year for comparison.
--
-- Run in SSMS against SDILive with Results To File (Query > Results To > Results to File), tab delimited, and send
-- the file back. customer_year_end_xlsx.py turns it into the workbook. Five grids, each row starting with its label:
--   CHECK    what was found
--   ACCOUNT  the accounts included, and how (name / part code)
--   LINE     every order line, last year and this year
--   WO       the works orders for those parts: completed since 1 Jan last year, and open ones
--   PART     each part's description and Access standard costs
-- Expect a minute.
USE SDILive;
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

DECLARE @name_like varchar(60) = '%XXXXX%';                                -- <- the customer's name
DECLARE @part_like varchar(30) = 'XXXXX-%';                                -- <- their part-code prefix, or ''
DECLARE @year_from date = DATEFROMPARTS(YEAR(GETDATE()), 1, 1);            -- this year, 1 Jan
DECLARE @today     date = CAST(GETDATE() AS date);
DECLARE @prev_from date = DATEADD(year, -1, @year_from);                   -- last year, 1 Jan

-- the accounts whose name matches
IF OBJECT_ID('tempdb..#acc') IS NOT NULL DROP TABLE #acc;
SELECT LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT AS code, MAX(LTRIM(RTRIM(a.CUNAME))) AS name
INTO #acc
FROM dbo.SL_ACCOUNTS a
WHERE a.CUNAME LIKE @name_like
GROUP BY LTRIM(RTRIM(a.CUCODE));

-- every order line since 1 Jan last year: on those accounts, or (any account) for a part with their prefix
IF OBJECT_ID('tempdb..#lines') IS NOT NULL DROP TABLE #lines;
SELECT LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT                          AS account,
       CASE WHEN k.code IS NOT NULL THEN 'name' ELSE 'part code' END                       AS found_by,
       LTRIM(RTRIM(c.COR_PART_ONLY)) COLLATE DATABASE_DEFAULT                              AS part,
       CAST(c.COR_ORDER_DATE AS date)                                                      AS order_date,
       LTRIM(RTRIM(ISNULL(c.COR_OUR_NUMBER, '')))                                          AS order_no,
       c.COR_LINE_NUM                                                                      AS line,
       REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_ORDER, ''))), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ')
                                                                                           AS customer_po,
       CAST(c.COR_QTY_ORDERED AS decimal(18, 3))                                           AS qty_ordered,
       CAST(ISNULL(c.COR_QTY_DELIVERED, 0) AS decimal(18, 3))                              AS qty_delivered,
       -- the price the order is worth: discounted price per its 'per' quantity, else the original (as vw_SOH_V2)
       CAST(COALESCE(
            CASE WHEN ISNULL(c.COR_DISC_PRICE, 0) <> 0
                 THEN c.COR_DISC_PRICE / NULLIF(CAST(c.COR_DISC_PRICE_PER AS decimal(18, 6)), 0) END,
            CASE WHEN ISNULL(c.COR_ORIG_PRICE, 0) <> 0
                 THEN c.COR_ORIG_PRICE / NULLIF(CAST(c.COR_ORIG_PRICE_PER AS decimal(18, 6)), 0) END,
            0) AS decimal(18, 5))                                                          AS unit_price,
       LTRIM(RTRIM(ISNULL(c.COR_CURRENCY, '')))                                            AS currency,
       CAST(c.COR_CUSTOMER_DUE AS date)                                                    AS customer_due,
       LTRIM(RTRIM(ISNULL(c.COR_ORDER_STATUS, '')))                                        AS line_status
INTO #lines
FROM dbo.ASC_COR_TBL c
LEFT JOIN #acc k ON k.code = LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT
WHERE c.COR_ORDER_DATE >= @prev_from AND c.COR_ORDER_DATE < DATEADD(day, 1, @today)
  AND LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> ''
  AND (k.code IS NOT NULL OR (@part_like <> '' AND LTRIM(RTRIM(c.COR_PART_ONLY)) LIKE @part_like));

IF OBJECT_ID('tempdb..#parts') IS NOT NULL DROP TABLE #parts;
SELECT DISTINCT part INTO #parts FROM #lines;

-- the works orders for those parts (whoever they were made for): completed since 1 Jan last year, and open
IF OBJECT_ID('tempdb..#wo') IS NOT NULL DROP TABLE #wo;
SELECT LTRIM(RTRIM(w.WOR_ORDER))                                                           AS wo,
       LTRIM(RTRIM(w.WOR_ITEM_ONLY)) COLLATE DATABASE_DEFAULT                              AS part,
       RTRIM(ISNULL(w.WOR_ORDER_TYPE, ''))                                                 AS order_type,
       LTRIM(RTRIM(ISNULL(w.WOR_PARENT_ORDER, '')))                                        AS parent_order,
       LTRIM(RTRIM(ISNULL(w.WOR_CUSTOMER, '')))                                            AS customer,
       LTRIM(RTRIM(ISNULL(w.WOR_SALORD, '')))                                              AS sales_order,
       RTRIM(ISNULL(w.WOR_STATUS, ''))                                                     AS status,
       CAST(w.WOR_CREATED_DATE AS date)                                                    AS created,
       CAST(w.WOR_DATE_SCHED AS date)                                                      AS scheduled,
       CAST(w.WOR_DONE_DATE AS date)                                                       AS done,
       CAST(CASE WHEN ISNULL(w.WOR_AMD_QTY, 0) > 0 THEN w.WOR_AMD_QTY ELSE w.WOR_ORIG_QTY END AS decimal(18, 3))
                                                                                           AS qty_planned,
       CAST(ISNULL(w.WOR_GOOD_QTY, 0) AS decimal(18, 3))                                   AS qty_good,
       CAST(ISNULL(w.WOR_REJECTED_QTY, 0) AS decimal(18, 3))                               AS qty_rejected,
       CAST(ISNULL(w.WOR_SCRAP_QTY, 0) AS decimal(18, 3))                                  AS qty_scrap,
       CAST(ISNULL(w.WOR_BOOKED_MAT_COST, 0) AS decimal(18, 2))                            AS booked_mat,
       CAST(ISNULL(w.WOR_BOOKED_LAB_COST, 0) AS decimal(18, 2))                            AS booked_lab,
       CAST(ISNULL(w.WOR_BOOKED_SC_COST, 0) AS decimal(18, 2))                             AS booked_subcon
INTO #wo
FROM dbo.ASC_WOR_TBL w
JOIN #parts p ON p.part = LTRIM(RTRIM(w.WOR_ITEM_ONLY)) COLLATE DATABASE_DEFAULT
WHERE (w.WOR_STATUS = 'C' AND COALESCE(w.WOR_DONE_DATE, w.WOR_DATE_SCHED) >= @prev_from)
   OR LTRIM(RTRIM(ISNULL(w.WOR_STATUS, ''))) = '';

-- CHECK: if LINE is 0, the name or prefix didn't match - check them in the sales ledger
SELECT 'CHECK' AS grid, CONVERT(varchar(19), GETDATE(), 120) AS run_at, @name_like AS name_like,
       @part_like AS part_like, @prev_from AS last_year_from, @year_from AS this_year_from, @today AS to_date,
       (SELECT COUNT(*) FROM #acc) AS accounts_by_name,
       (SELECT COUNT(DISTINCT account) FROM #lines WHERE found_by = 'part code') AS other_accounts_by_part_code,
       (SELECT COUNT(*) FROM #lines) AS order_lines, (SELECT COUNT(*) FROM #parts) AS parts,
       (SELECT COUNT(*) FROM #wo) AS works_orders;

-- ACCOUNT: every account included, with its name, and how it was found
SELECT 'ACCOUNT' AS grid, x.account, ISNULL(LTRIM(RTRIM(a.CUNAME)), '') AS name, x.found_by,
       COUNT(*) AS order_lines, MIN(x.order_date) AS first_order, MAX(x.order_date) AS last_order
FROM #lines x
LEFT JOIN dbo.SL_ACCOUNTS a ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = x.account
GROUP BY x.account, a.CUNAME, x.found_by
UNION ALL                                                                 -- name matches with no orders
SELECT 'ACCOUNT', k.code, k.name, 'name (no orders in the period)', 0, NULL, NULL
FROM #acc k WHERE NOT EXISTS (SELECT 1 FROM #lines x WHERE x.account = k.code)
ORDER BY 4, 2;

SELECT 'LINE' AS grid, account, found_by, part, order_date, order_no, line, customer_po, qty_ordered, qty_delivered,
       unit_price, currency, customer_due, line_status
FROM #lines ORDER BY part, order_date, order_no, line;

SELECT 'WO' AS grid, wo, part, order_type, parent_order, customer, sales_order, status, created, scheduled, done,
       qty_planned, qty_good, qty_rejected, qty_scrap, booked_mat, booked_lab, booked_subcon
FROM #wo ORDER BY part, COALESCE(done, scheduled);

SELECT 'PART' AS grid, p.part,
       REPLACE(REPLACE(REPLACE(ISNULL(MAX(LTRIM(RTRIM(m.PMA_DESC_1))), ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS description,
       REPLACE(REPLACE(REPLACE(ISNULL(MAX(LTRIM(RTRIM(m.PMA_DESC))), ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ')   AS description_full,
       MAX(CAST(ISNULL(m.PMA_COST_MAT, 0) AS decimal(18, 5)))   AS cost_mat,
       MAX(ISNULL(m.PMA_COST_MAT_PER, 0))                       AS cost_mat_per,
       MAX(CAST(ISNULL(m.PMA_COST, 0) AS decimal(18, 5)))       AS cost,
       MAX(ISNULL(m.PMA_COST_PER, 0))                           AS cost_per,
       MAX(CAST(ISNULL(m.PMA_WORKS_COST, 0) AS decimal(18, 5))) AS works_cost
FROM #parts p
LEFT JOIN dbo.ASC_PMA_TBL m ON LTRIM(RTRIM(m.PMA_PART_ONLY)) COLLATE DATABASE_DEFAULT = p.part
GROUP BY p.part
ORDER BY p.part;
