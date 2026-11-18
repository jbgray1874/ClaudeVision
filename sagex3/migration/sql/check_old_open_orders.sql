-- check_old_open_orders.sql  -  READ ONLY, changes nothing.
--
-- Have Purchasing and Customer Service closed the old orders in Access?
-- (Run 4 actions, 11 Nov: Purchasing_2023_POs_to_review.xlsx and
--  CustomerService_2023_SOs_to_review.xlsx; runbook 19.10.)
--
-- It reads the same views the migration extract reads (migration.vw_SOH_V2 / vw_POH_V2),
-- so "still open" here means "would load into Sage X3 again".
--
-- At Run 4 (4 Nov extract):
--   POs dated before 2024:  17 lines on 8 POs
--   SOs dated before 2024: 385 lines on 115 order references
--
-- Grids (Results to Grid is fine; or To File, tab delimited, for the comparison):
--   SUMMARY  open lines and orders by order year, for SO and PO
--   OLD_PO   every open PO line dated before 2024
--   OLD_SO   every open SO line dated before 2024
--
-- Compare OLD_PO / OLD_SO with the two review lists: an order on the list but not here
-- has been closed; one still here is either marked "still open" by the team or not done yet.

SELECT 'SUMMARY' AS grid, 'SO' AS ledger, LEFT(ORDDAT, 4) AS order_year,
       COUNT(*) AS open_lines, COUNT(DISTINCT REF_ORDER_NUMBER) AS orders
FROM migration.vw_SOH_V2
GROUP BY LEFT(ORDDAT, 4)
UNION ALL
SELECT 'SUMMARY', 'PO', LEFT(ORDDAT, 4), COUNT(*), COUNT(DISTINCT REF_ORDER_NUMBER)
FROM migration.vw_POH_V2
GROUP BY LEFT(ORDDAT, 4)
ORDER BY ledger, order_year;

SELECT 'OLD_PO' AS grid, REF_ORDER_NUMBER AS access_po, ORDDAT, EXTRCPDAT, REF_ACCESS_SUPPLIER,
       ITMREF, QTYUOM, GROPRI, CAST(QTYUOM * GROPRI AS decimal(18, 2)) AS value
FROM migration.vw_POH_V2
WHERE ORDDAT < '20240101'
ORDER BY REF_ORDER_NUMBER, POPLIN;

SELECT 'OLD_SO' AS grid, REF_ORDER_NUMBER AS access_order, ORDDAT, DEMDLVDAT, REF_ACCESS_CUSTOMER,
       CUSORDREF, ITMREF, QTY, GROPRI, CAST(QTY * GROPRI AS decimal(18, 2)) AS value, REF_ORDER_STATUS
FROM migration.vw_SOH_V2
WHERE ORDDAT < '20240101'
ORDER BY REF_ORDER_NUMBER, SOPLIN;
