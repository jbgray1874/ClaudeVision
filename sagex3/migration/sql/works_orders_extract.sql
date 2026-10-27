-- works_orders_extract.sql  -  READ ONLY, changes nothing
--
-- The open works orders for YA004MFG. From works_orders_discovery.sql:
--   WOR_STATUS   C = complete (54,913), blank = open (744)
--   WOR_ORIG_QTY quantity ordered, WOR_AMD_QTY amended quantity, WOR_GOOD_QTY made so far
--   WOR_DATE_SCHED scheduled date, WOR_FIRST_DATE / WOR_CREATED_DATE for the start
--   WOR_ORDER_TYPE WS (54,339), WP (1,317), WR (1)
-- Grids 1, 3 and 4 settle how quantity, dates and order type are read. Grid 2 is the list.
-- Four grids. Paste them all back (grid 2 is about 744 rows).
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. The open works orders in outline =====
SELECT RTRIM(WOR_ORDER_TYPE) AS order_type,
       COUNT(*) AS orders,
       SUM(CASE WHEN ISNULL(NULLIF(WOR_AMD_QTY, 0), WOR_ORIG_QTY) - WOR_GOOD_QTY > 0 THEN 1 ELSE 0 END) AS with_qty_to_make,
       SUM(CASE WHEN WOR_GOOD_QTY > 0 THEN 1 ELSE 0 END) AS part_made,
       SUM(CASE WHEN WOR_BOOKED_MAT_COST + WOR_BOOKED_LAB_COST + WOR_BOOKED_SC_COST > 0 THEN 1 ELSE 0 END) AS with_cost_booked,
       SUM(CASE WHEN WOR_DATE_SCHED < CAST(GETDATE() AS date) THEN 1 ELSE 0 END) AS scheduled_in_past,
       SUM(CASE WHEN LTRIM(RTRIM(ISNULL(WOR_PARENT_ORDER, ''))) <> '' THEN 1 ELSE 0 END) AS has_parent_order,
       SUM(CASE WHEN WOR_FIRST_DATE IS NULL THEN 1 ELSE 0 END) AS no_first_date,
       CAST(SUM(WOR_BOOKED_MAT_COST + WOR_BOOKED_LAB_COST + WOR_BOOKED_SC_COST) AS decimal(18, 2)) AS cost_booked
FROM dbo.ASC_WOR_TBL
WHERE LTRIM(RTRIM(ISNULL(WOR_STATUS, ''))) = ''
GROUP BY RTRIM(WOR_ORDER_TYPE)
ORDER BY 2 DESC;

-- ===== 2. THE LIST: every open works order =====
SELECT WOR_UNIQUE,
       LTRIM(RTRIM(WOR_ORDER))        AS works_order,
       LTRIM(RTRIM(WOR_PARENT_ORDER)) AS parent_order,
       LTRIM(RTRIM(WOR_ITEM_ONLY))    AS product,
       LTRIM(RTRIM(WOR_ITEM_REV))     AS rev,
       LTRIM(RTRIM(WOR_SALORD))       AS sales_order,
       LTRIM(RTRIM(WOR_CUSTOMER))     AS customer,
       RTRIM(WOR_ORDER_TYPE)          AS order_type,
       CAST(WOR_ORIG_QTY AS decimal(18, 3))     AS orig_qty,
       CAST(WOR_AMD_QTY AS decimal(18, 3))      AS amd_qty,
       CAST(WOR_GOOD_QTY AS decimal(18, 3))     AS good_qty,
       CAST(WOR_REJECTED_QTY AS decimal(18, 3)) AS rejected_qty,
       CAST(WOR_SCRAP_QTY AS decimal(18, 3))    AS scrap_qty,
       CONVERT(varchar(8), WOR_CREATED_DATE, 112)      AS created,
       CONVERT(varchar(8), WOR_FIRST_DATE, 112)        AS first_date,
       CONVERT(varchar(8), WOR_MRP_DATE, 112)          AS mrp_date,
       CONVERT(varchar(8), WOR_DATE_SCHED, 112)        AS scheduled,
       CONVERT(varchar(8), WOR_LAST_MAT_DUE_DATE, 112) AS last_mat_due,
       CONVERT(varchar(8), WOR_DONE_DATE, 112)         AS done_date,
       RTRIM(WOR_MAT_STAT)            AS mat_stat,
       CAST(WOR_BOOKED_MAT_COST AS decimal(18, 2)) AS booked_mat,
       CAST(WOR_BOOKED_LAB_COST AS decimal(18, 2)) AS booked_lab,
       CAST(WOR_BOOKED_SC_COST AS decimal(18, 2))  AS booked_subcon,
       LTRIM(RTRIM(WOR_DEST_WH))      AS dest_wh,
       LTRIM(RTRIM(WOR_DEST_BIN))     AS dest_bin
FROM dbo.ASC_WOR_TBL
WHERE LTRIM(RTRIM(ISNULL(WOR_STATUS, ''))) = ''
ORDER BY WOR_DATE_SCHED, WOR_ORDER;

-- ===== 3. How the amended quantity is used, on completed orders =====
-- Tells us whether "to make" is the amended quantity when there is one.
SELECT CASE WHEN WOR_AMD_QTY = 0 THEN 'no amendment'
            WHEN WOR_GOOD_QTY = WOR_AMD_QTY THEN 'made = amended'
            WHEN WOR_GOOD_QTY = WOR_ORIG_QTY THEN 'made = original'
            ELSE 'made = neither' END AS pattern,
       COUNT(*) AS orders
FROM dbo.ASC_WOR_TBL
WHERE WOR_STATUS = 'C' AND WOR_DATE_SCHED >= '20250101'
GROUP BY CASE WHEN WOR_AMD_QTY = 0 THEN 'no amendment'
              WHEN WOR_GOOD_QTY = WOR_AMD_QTY THEN 'made = amended'
              WHEN WOR_GOOD_QTY = WOR_ORIG_QTY THEN 'made = original'
              ELSE 'made = neither' END
ORDER BY 2 DESC;

-- ===== 4. What a WP order is: the ten most recent =====
SELECT TOP 10 LTRIM(RTRIM(WOR_ORDER)) AS works_order, LTRIM(RTRIM(WOR_ITEM_ONLY)) AS product,
       LTRIM(RTRIM(WOR_SALORD)) AS sales_order, CAST(WOR_ORIG_QTY AS decimal(18, 3)) AS orig_qty,
       CAST(WOR_GOOD_QTY AS decimal(18, 3)) AS good_qty, RTRIM(WOR_STATUS) AS status,
       CONVERT(varchar(8), WOR_DATE_SCHED, 112) AS scheduled, LTRIM(RTRIM(WOR_PARENT_ORDER)) AS parent_order
FROM dbo.ASC_WOR_TBL
WHERE RTRIM(WOR_ORDER_TYPE) = 'WP'
ORDER BY WOR_DATE_SCHED DESC;
GO
