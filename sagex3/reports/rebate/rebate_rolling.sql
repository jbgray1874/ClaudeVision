-- rebate_rolling.sql  -  READ ONLY. Rebate rolling report (REP-22, SCRUM-275): the invoiced lines of the
-- rebate parts for the 12 months to date plus the month before (the Access report lists that month's
-- lines with no value). Same joins as Access's own view dbo.UDEF_INVOICED_SALES (invoice line TBI_TBL ->
-- order line COR_TBL -> customer SL_ACCOUNTS2), with real dates instead of text.
-- Results to file, tab delimited, WITH headers: <run>/rebate_lines.txt. Then:
--   python build_rebate_report.py rebate_lines.txt <out folder>
-- Part list: keep in step with rebate_parts.csv.
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

DECLARE @from date = DATEADD(month, -12, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1));

SELECT LTRIM(RTRIM(i.TBI_CUS))                                   AS customer_code,
       LTRIM(RTRIM(ISNULL(a.CUNAME, '')))                        AS customer_name,
       LTRIM(RTRIM(i.TBI_PART_ONLY))                             AS part_code,
       LTRIM(RTRIM(ISNULL(p.PMA_DESC_1, '')))                    AS description,   -- the part's description
       CAST(c.COR_PRICE_PER AS decimal(18, 5))                   AS price_per,
       CAST(i.TBI_QTY AS decimal(18, 5))                         AS quantity,
       LTRIM(RTRIM(i.TBI_INVOICE_NO))                            AS invoice_no,
       CONVERT(varchar(10), i.TBI_INVOICE_DATE, 23)              AS invoice_date,
       CONVERT(varchar(10), c.COR_CUSTOMER_DUE, 23)              AS due_date,
       LTRIM(RTRIM(i.TBI_OUR))                                   AS order_no,
       CONVERT(varchar(10), c.COR_ORDER_DATE, 23)                AS order_date,
       LTRIM(RTRIM(ISNULL(c.COR_PROJECT, '')))                   AS project_no,
       CAST(ISNULL(s.CU_USRNUM1, 0) AS decimal(9, 3))            AS customer_rebate_pct   -- Access's own per-customer rebate %
FROM TBI_TBL i
LEFT JOIN COR_TBL c       ON i.TBI_PART_ONLY = c.COR_PART_ONLY AND i.TBI_PART_REV = c.COR_PART_REV
                         AND c.COR_OUR_NUMBER = i.TBI_OUR AND c.COR_SUB = i.TBI_SUB
LEFT JOIN SL_ACCOUNTS2 s  ON s.CUCODE2 = i.TBI_CUS COLLATE LATIN1_GENERAL_BIN
LEFT JOIN SL_ACCOUNTS a   ON a.CUCODE = i.TBI_CUS COLLATE LATIN1_GENERAL_BIN
OUTER APPLY (SELECT TOP 1 PMA_DESC_1 FROM PMA_TBL WHERE PMA_PART_ONLY = i.TBI_PART_ONLY) p   -- one row per part, never duplicates
WHERE i.TBI_INVOICE_DATE >= @from
  AND LTRIM(RTRIM(i.TBI_PART_ONLY)) IN (
      '10932-00-GA1 HAR', '10932-00-GA1 M&M', '10932-00-GA HVL', '10932-00-GA1 KEN', '10932-00-GA1 B/B',
      '10932-00-GA1 BEL', '10932-00-GA1 CAD', '10932-00-GA1 TOB', '10932-00-GA1 BRU', '10932-00-GA1 NES',
      '10932-00-GA1 ROW', '10932-00-GA1 GOU', '10932-00-GA1 VOL', '10932-00-GA1 SH', '10932-00-GA1 TET',
      '10932-00-GA1 QW', '10932-00-GA1 COM', '10932-00-GA1 HEI', 'HHA-INSTALL M&M', 'LRS01- RIBENA',
      'LRS01- LUCOZADE', 'WMM01-GOALPOST')
ORDER BY customer_code, part_code, i.TBI_INVOICE_DATE;
