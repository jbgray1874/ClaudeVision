-- live_enquiry_discovery_2.sql - READ ONLY (SELECTs only). Follow-up to live_enquiry_discovery.sql (15 Nov).
-- Grid 1 found: the CRM sales-opportunity / pipeline / outstanding-estimate views, ORD_HEADER with OH_PROBABILITY,
-- OH_QUOTE_DATE and OH_ESTIMATE_DROP_DATE, project tables (CST_PROJECT views, ASC_ORC_PROJECTS), leads (DLR_LEADUPDATE).
-- This shows which of them actually hold data, how recent it is, what they're built on, and a few recent rows.
-- SSMS: Results to Text (tab delimited), run, save as live_enquiry_discovery_2.rpt
USE SDILive;
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

DECLARE @objs TABLE (n sysname PRIMARY KEY);
INSERT @objs VALUES ('AA_CRM_SALES_OPPS_HEADER_SIMPLE_VIEW'), ('AA_CRM_SALES_OPPS_DETAIL_SIMPLE_VIEW'),
  ('AA_CRM_OUTSTANDING_EST_HEADER_SIMPLE_VIEW'), ('AA_CRM_OUTSTANDING_EST_DETAIL_SIMPLE_VIEW'), ('AA_CRM_PIPELINE_SIMPLE_VIEW'),
  ('AA_CRM_CURRENT_PIPELINE_SIMPLE_VIEW'), ('AA_REP_CRM_SALES_OPPORTUNITIES_VIEW'), ('AA_REP_CRM_PROSPECT_LIST_VIEW'),
  ('AA_CRM_ACCOUNT_VIEW'), ('AA_CRM_CONTACTS_SIMPLE_VIEW'), ('AA_CRM_CONTACT_HISTORY_SIMPLE_VIEW'), ('AA_CRM_MY_TASKS_SIMPLE_VIEW'),
  ('AA_REP_CRM_ESTIMATE_VIEW'), ('AA_CST_PROJECT_VIEW'), ('AA_CST_PROJECT_SIMPLE_VIEW'), ('ASC_ORC_PROJECTS'),
  ('UDEF_SALES_ORDER_PROJECT_NUMBER'), ('UDEF_PROJECT_DETAIL'), ('UDEF_WOR_PROJECT'), ('ASC_EDT_SALES_QUOTE_BOOK'),
  ('DLR_LEADUPDATE'), ('ORD_HEADER'), ('AA_AOI_PIPELINE_ANALYSIS'), ('AA_AOI_CUSTOMER_PROSPECT_VIEW');

-- 1. Row count of each (views counted by running them; an error is reported, not raised)
DECLARE @n sysname, @c bigint, @q nvarchar(max);
DECLARE @counts TABLE (n sysname, row_count bigint NULL, err nvarchar(400) NULL);
DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT n FROM @objs WHERE OBJECT_ID('dbo.' + n) IS NOT NULL;
OPEN cur; FETCH NEXT FROM cur INTO @n;
WHILE @@FETCH_STATUS = 0
BEGIN
  BEGIN TRY
    SET @q = N'SELECT @c = COUNT_BIG(*) FROM dbo.' + QUOTENAME(@n);
    EXEC sys.sp_executesql @q, N'@c bigint OUTPUT', @c = @c OUTPUT;
    INSERT @counts VALUES (@n, @c, NULL);
  END TRY
  BEGIN CATCH
    INSERT @counts VALUES (@n, NULL, LEFT(ERROR_MESSAGE(), 400));
  END CATCH
  FETCH NEXT FROM cur INTO @n;
END
CLOSE cur; DEALLOCATE cur;
SELECT 'COUNT' AS grid, n, row_count, err FROM @counts ORDER BY row_count DESC;

-- 2. Columns of ORD_HEADER and of the opportunity / outstanding-estimate / project views (to map onto X3)
SELECT 'COLS' AS grid, o.name AS object_name, c.column_id, c.name AS column_name, t.name AS data_type, c.max_length
FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE o.name IN ('ORD_HEADER', 'AA_CRM_SALES_OPPS_HEADER_SIMPLE_VIEW', 'AA_CRM_OUTSTANDING_EST_HEADER_SIMPLE_VIEW',
                 'AA_CST_PROJECT_VIEW', 'DLR_LEADUPDATE', 'ASC_ORC_PROJECTS')
ORDER BY o.name, c.column_id;

-- 3. What the key views are built on (their definitions)
SELECT 'DEF' AS grid, o.name, REPLACE(REPLACE(OBJECT_DEFINITION(o.object_id), CHAR(13), ' '), CHAR(10), ' ') AS definition
FROM sys.objects o
WHERE o.name IN ('AA_CRM_SALES_OPPS_HEADER_SIMPLE_VIEW', 'AA_CRM_OUTSTANDING_EST_HEADER_SIMPLE_VIEW', 'AA_CRM_PIPELINE_SIMPLE_VIEW',
                 'AA_CST_PROJECT_VIEW', 'ASC_ORC_PROJECTS', 'UDEF_SALES_ORDER_PROJECT_NUMBER');

-- 4. ORD_HEADER: how many orders carry quote / estimate data, by year of the quote date
SELECT 'ORDQ' AS grid, YEAR(OH_QUOTE_DATE) AS quote_year, COUNT(*) AS orders,
       SUM(CASE WHEN OH_PROBABILITY IS NOT NULL AND OH_PROBABILITY <> 0 THEN 1 ELSE 0 END) AS with_probability,
       SUM(CASE WHEN OH_ESTIMATE_DROP_DATE IS NOT NULL THEN 1 ELSE 0 END) AS with_estimate_drop_date
FROM dbo.ORD_HEADER
GROUP BY YEAR(OH_QUOTE_DATE) ORDER BY quote_year DESC;

-- 5. A few of the most recent rows from each object that holds data (read-only dynamic SELECTs)
DECLARE @s nvarchar(max) = N'';
SELECT @s = @s + N'BEGIN TRY SELECT ''RECENT'' AS grid, ''' + n + N''' AS source, t.* FROM (SELECT TOP 8 * FROM dbo.'
       + QUOTENAME(n) + N') t; END TRY BEGIN CATCH SELECT ''RECENT'' AS grid, ''' + n + N''' AS source, ERROR_MESSAGE() AS err; END CATCH;' + CHAR(10)
FROM @counts WHERE row_count > 0 AND n <> 'ORD_HEADER';
IF @s <> N'' EXEC sys.sp_executesql @s;
SELECT 'RECENT' AS grid, 'ORD_HEADER (latest quote dates)' AS source, t.*
FROM (SELECT TOP 8 * FROM dbo.ORD_HEADER WHERE OH_QUOTE_DATE IS NOT NULL ORDER BY OH_QUOTE_DATE DESC) t;
