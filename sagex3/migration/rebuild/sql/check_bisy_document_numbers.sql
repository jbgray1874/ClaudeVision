-- check_bisy_document_numbers.sql  (read-only: SELECTs only, nothing is changed)
--
-- Why (Ethan / Jim, 11 Nov, Run 4): YA004BISY uses the Access document number (5 and six digits,
-- e.g. 5029976) as the X3 document. 259 open supplier items (GBP 1,332,793.58 on the 4 Nov
-- extract) have none, so the supplier's reference stood in. Acuity want it confirmed that Access
-- really holds no document number for them before deciding what to do.
-- Ethan also says rows that share one Access number are lines of one invoice (e.g. 5028370,
-- six rows). Query 2 shows those rows in full so we can see what Access holds for each.
--
-- Run on SDILive, results to grid, copy each grid WITH headers into the one text file,
-- query 1 first. Save as check_bisy_document_numbers.txt.
--
-- Expected:  query 1 - about 259 rows (all open items, whatever their supplier); every
--            column of PL_TRANSACTIONS, so we can see whether a 5xxxxxx number sits anywhere else.
--            query 2 - 6 rows for 5028370 (DIR500), one per supplier invoice.

-- 1. open purchase ledger items with no Access document number in any reference field
SELECT t.*
FROM dbo.PL_TRANSACTIONS t
WHERE t.PT_UNALLOCATED <> 0
  AND LTRIM(RTRIM(ISNULL(t.PT_COPYSUPP, ''))) <> ''
  AND LTRIM(RTRIM(ISNULL(CAST(t.PT_HEADER_REF   AS varchar(50)), ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
  AND LTRIM(RTRIM(ISNULL(CAST(t.PT_HEADER_REF2  AS varchar(50)), ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
  AND LTRIM(RTRIM(ISNULL(CAST(t.PT_ORDER_NUMBER AS varchar(50)), ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
ORDER BY t.PT_COPYSUPP, t.PT_DATE;

-- 2. Ethan's example: every row carrying Access number 5028370, open or not
SELECT t.*
FROM dbo.PL_TRANSACTIONS t
WHERE '5028370' IN (LTRIM(RTRIM(ISNULL(CAST(t.PT_HEADER_REF   AS varchar(50)), ''))),
                    LTRIM(RTRIM(ISNULL(CAST(t.PT_HEADER_REF2  AS varchar(50)), ''))),
                    LTRIM(RTRIM(ISNULL(CAST(t.PT_ORDER_NUMBER AS varchar(50)), ''))))
ORDER BY t.PT_DATE, t.PT_PRIMARY;
