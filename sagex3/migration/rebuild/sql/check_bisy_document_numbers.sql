-- Read-only. Open supplier items with no Access document number (5 + six digits) in any reference field.
-- Expect about 259 rows (11 Nov, Ethan / Jim). Copy the grid with headers.
SELECT PT_PRIMARY, PT_COPYSUPP, PT_DATE, PT_TRANTYPE, PT_HEADER_REF, PT_HEADER_REF2, PT_ORDER_NUMBER,
       PT_UNALLOCATED, PT_DESCRIPTION
FROM dbo.PL_TRANSACTIONS
WHERE PT_UNALLOCATED <> 0
  AND LTRIM(RTRIM(ISNULL(PT_HEADER_REF, ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
  AND LTRIM(RTRIM(ISNULL(PT_HEADER_REF2, ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
  AND LTRIM(RTRIM(ISNULL(PT_ORDER_NUMBER, ''))) NOT LIKE '5[0-9][0-9][0-9][0-9][0-9][0-9]'
ORDER BY PT_COPYSUPP, PT_DATE;
