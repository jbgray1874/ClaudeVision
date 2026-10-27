-- customer_code_list_for_sue.sql  -  READ ONLY, changes nothing
--
-- Old Access customer code -> new Sage X3 customer code, for Customer Services.
-- Every Access customer, with its new code from migration.XREF_SAGE_BPC (the cross-reference
-- every migration file was built from), or a reason why there is no new code yet.
--
-- Run xref_sage_codes.sql first if migration.XREF_SAGE_BPC is not there.
-- One grid. Results To File, tab delimited, and send it back.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

WITH orders AS (
    SELECT LTRIM(RTRIM(COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT AS code,
           MAX(COR_ORDER_DATE) AS last_order,
           SUM(CASE WHEN ISNULL(COR_QTY_ORDERED, 0) > ISNULL(COR_QTY_DELIVERED, 0) THEN 1 ELSE 0 END) AS open_lines
    FROM dbo.ASC_COR_TBL
    GROUP BY LTRIM(RTRIM(COR_CUSTOMER_CODE))
), ledger AS (
    SELECT LTRIM(RTRIM(ST_COPYCUST)) COLLATE DATABASE_DEFAULT AS code,
           MAX(ST_DATE) AS last_transaction,
           SUM(CASE WHEN ST_UNALLOCATED <> 0 THEN 1 ELSE 0 END) AS open_items,
           CAST(SUM(ST_UNALLOCATED) AS decimal(18, 2)) AS open_balance
    FROM dbo.SL_TRANSACTIONS
    GROUP BY LTRIM(RTRIM(ST_COPYCUST))
)
SELECT LTRIM(RTRIM(a.CUCODE))                         AS old_code,
       LTRIM(RTRIM(a.CUNAME))                         AS customer_name,
       ISNULL(x.SAGE_CODE, '')                        AS new_code,
       ISNULL(x.SAGE_NAME, '')                        AS new_name,
       CASE WHEN x.SAGE_CODE IS NOT NULL THEN 'New code in Sage X3'
            WHEN ISNULL(l.open_items, 0) > 0 OR ISNULL(o.open_lines, 0) > 0
                 THEN 'No new code yet - has open items or orders, account to be created'
            WHEN o.last_order >= DATEADD(year, -2, GETDATE()) OR l.last_transaction >= DATEADD(year, -2, GETDATE())
                 THEN 'No new code - traded in the last 2 years, not in the customer load'
            ELSE 'No new code - not traded for 2 years, not migrated' END AS status,
       ISNULL(x.MATCHED_BY, '')                       AS matched_by,
       CONVERT(varchar(10), o.last_order, 23)         AS last_order,
       CONVERT(varchar(10), l.last_transaction, 23)   AS last_ledger_entry,
       ISNULL(l.open_items, 0)                        AS open_items,
       ISNULL(l.open_balance, 0)                      AS open_balance
FROM dbo.SL_ACCOUNTS a
LEFT JOIN migration.XREF_SAGE_BPC x ON x.ACCESS_CODE = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN orders o ON o.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN ledger l ON l.code = LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT
WHERE LTRIM(RTRIM(ISNULL(a.CUCODE, ''))) <> ''
ORDER BY CASE WHEN x.SAGE_CODE IS NOT NULL THEN 0 ELSE 1 END, a.CUCODE;
GO
