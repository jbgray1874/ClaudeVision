-- customer_parts_history.sql  -  READ ONLY (Access SupplyChain, SDILive). Written 20 Nov 2026.
-- Every part one customer account has ordered over the last 3 years, and which ones they've STOPPED ordering
-- (ordered in the 2 years before, nothing in the last 12 months). First asked for by Ian Knight (19 Nov).
--
-- Set @customer below (the Access customer code). The committed copy keeps a placeholder: customer codes and
-- names stay out of git. Run in SSMS against SDILive. Two result grids:
--   1. SUMMARY  one row per part: first / last ordered, orders and quantity before vs in the last 12 months, status
--   2. DETAIL   every order line, sorted by part, description, then order date
-- Copy each grid with headers (right-click > Copy with Headers) into its own Excel tab.
USE SDILive;
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

DECLARE @customer varchar(20) = 'XXXXX';                                   -- <- the customer code
DECLARE @today date = CAST(GETDATE() AS date);
DECLARE @from date = DATEADD(year, -3, @today);                            -- 3 years back
DECLARE @recent date = DATEADD(year, -1, @today);                          -- the last 12 months start here

IF OBJECT_ID('tempdb..#lines') IS NOT NULL DROP TABLE #lines;
SELECT LTRIM(RTRIM(c.COR_PART_ONLY))                              AS part,
       LTRIM(RTRIM(ISNULL(c.COR_PART_REV, '')))                   AS rev,
       LTRIM(RTRIM(ISNULL(p.PMA_DESC_1, '')))                     AS description,
       CAST(c.COR_ORDER_DATE AS date)                             AS order_date,
       LTRIM(RTRIM(c.COR_OUR_NUMBER))                             AS order_no,
       c.COR_LINE_NUM                                             AS line,
       CAST(c.COR_QTY_ORDERED AS decimal(18, 2))                  AS qty_ordered,
       CAST(ISNULL(c.COR_QTY_DELIVERED, 0) AS decimal(18, 2))     AS qty_delivered,
       CAST(c.COR_PRICE_PER AS decimal(18, 4))                    AS price_per,
       CAST(c.COR_CUSTOMER_DUE AS date)                           AS customer_due,
       LTRIM(RTRIM(ISNULL(c.COR_ORDER_STATUS, '')))               AS line_status
INTO #lines
FROM COR_TBL c
OUTER APPLY (SELECT TOP 1 PMA_DESC_1 FROM PMA_TBL WHERE PMA_PART_ONLY = c.COR_PART_ONLY) p   -- one row per part
WHERE LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) = @customer
  AND c.COR_ORDER_DATE >= @from
  AND LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> '';

-- 0. CHECK: what was found (if 0 lines, check the code; if the earliest date is well after 3 years ago,
--    older orders may be archived elsewhere - tell Claude)
SELECT 'CHECK' AS grid, @customer AS customer, COUNT(*) AS order_lines, COUNT(DISTINCT part) AS parts,
       MIN(order_date) AS earliest, MAX(order_date) AS latest, @from AS asked_from, @recent AS last_12_months_from
FROM #lines;

-- 1. SUMMARY: one row per part.
--    v2 (20 Nov, after the first run): many "stopped" parts were the same item re-coded and still ordered under
--    the new code (11019-BO-01-OS -> SRS-11019-BO-01, SRS-11196-03-GA -> 11196-03-GA OS, SRS-EL0999 -> SRS02-EL0999).
--    "core" = the code without a customer prefix (BOT-, SRS-, SRS02- ... up to the first hyphen when the code starts
--    with a letter) and without an ' OS' / '-OS' / ' CO' / ' CH' ending. A STOPPED part whose core is still ordered
--    under another code says so. Carriage, rework, installation etc. are marked "Not a product".
IF OBJECT_ID('tempdb..#parts') IS NOT NULL DROP TABLE #parts;
SELECT part, description,
       MIN(order_date)                                                        AS first_ordered,
       MAX(order_date)                                                        AS last_ordered,
       SUM(CASE WHEN order_date <  @recent THEN 1 ELSE 0 END)                 AS lines_2_years_before,
       SUM(CASE WHEN order_date <  @recent THEN qty_ordered ELSE 0 END)       AS qty_2_years_before,
       SUM(CASE WHEN order_date >= @recent THEN 1 ELSE 0 END)                 AS lines_last_12_months,
       SUM(CASE WHEN order_date >= @recent THEN qty_ordered ELSE 0 END)       AS qty_last_12_months,
       CAST('' AS varchar(60))                                                AS core
INTO #parts
FROM #lines
GROUP BY part, description;

UPDATE #parts SET core = CASE WHEN part LIKE '[A-Z]%-%' AND CHARINDEX('-', part) BETWEEN 2 AND 7
                              THEN SUBSTRING(part, CHARINDEX('-', part) + 1, 60) ELSE part END;
UPDATE #parts SET core = LEFT(core, LEN(core) - 3)
WHERE RIGHT(core, 3) IN (' OS', '-OS', '-0S', ' CO', ' CH') AND LEN(core) > 3;

SELECT p.part, p.description, p.first_ordered, p.last_ordered,
       p.lines_2_years_before, p.qty_2_years_before, p.lines_last_12_months, p.qty_last_12_months,
       CASE WHEN p.part IN ('CARRIAGE', 'CARRIAGE IN', 'DELIVERY', 'REWORK', 'ADDITIONAL COST', 'SDI-PROTO', 'MISC PRINT')
                 OR p.part LIKE '%INSTALLATION%' OR p.part LIKE '%RESPRAY%'      THEN 'Not a product (carriage, rework etc.)'
            WHEN p.last_ordered < @recent AND s.codes IS NOT NULL               THEN 'RE-CODED - still ordered as another code'
            WHEN p.last_ordered < @recent                                       THEN 'STOPPED - none in the last 12 months'
            WHEN p.first_ordered >= @recent                                     THEN 'NEW in the last 12 months'
            ELSE 'Still ordering' END                                           AS status,
       ISNULL(STUFF(s.codes, 1, 2, ''), '')                                     AS similar_code_still_ordered
FROM #parts p
OUTER APPLY (SELECT (SELECT ', ' + q.part FROM #parts q
                     WHERE q.core = p.core AND q.part <> p.part AND q.last_ordered >= @recent
                     ORDER BY q.part FOR XML PATH(''), TYPE).value('.', 'varchar(max)') AS codes) s   -- keeps & as &
ORDER BY CASE WHEN p.part IN ('CARRIAGE', 'CARRIAGE IN', 'DELIVERY', 'REWORK', 'ADDITIONAL COST', 'SDI-PROTO', 'MISC PRINT')
                   OR p.part LIKE '%INSTALLATION%' OR p.part LIKE '%RESPRAY%' THEN 4
              WHEN p.last_ordered < @recent AND s.codes IS NULL THEN 0          -- truly stopped first
              WHEN p.last_ordered < @recent THEN 1                              -- re-coded
              WHEN p.first_ordered >= @recent THEN 3 ELSE 2 END, p.part, p.description;
DROP TABLE #parts;

-- 2. DETAIL: every order line, by part, description, then date
SELECT part, rev, description, order_date, order_no, line, qty_ordered, qty_delivered, price_per,
       customer_due, line_status
FROM #lines
ORDER BY part, description, order_date, order_no, line;

DROP TABLE #lines;
