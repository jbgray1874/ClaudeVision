-- products_gap.sql  -  READ ONLY, changes nothing
--
-- The BOM load references 30,706 distinct product codes. The item load holds 16,395.
-- 14,303 codes the BOM needs are not in the item load, which costs us 33,618 of the
-- 63,739 BOM lines - 53% of the structure. Only 8 of those 14,303 are a cleansing
-- artefact, so this is not a formatting problem: the item extract is narrower than the
-- BOM. This settles whether that is right.
--
-- Returns 6 grids. All small except grid 2, which is the text of a view - paste it in
-- full, it is the thing that tells us what was filtered out.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. What the migration schema holds, and how big each object is =====
SELECT o.type_desc, o.name AS [object],
       ISNULL((SELECT SUM(p.rows) FROM sys.partitions p
                WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)), -1) AS table_rows
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name = 'migration' AND o.type IN ('U', 'V')
ORDER BY o.name;

-- ===== 1b. The BOM view's own columns, so the joins below can be checked at a glance =====
SELECT c.name AS [column], ty.name AS [type], c.max_length
FROM sys.columns c
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('migration.vw_BOMP')
ORDER BY c.column_id;

-- ===== 2. The definition of whatever built the item file - this names the filter =====
SELECT o.name AS [object], OBJECT_DEFINITION(o.object_id) AS [definition]
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name = 'migration' AND o.type = 'V'
  AND (o.name LIKE '%ITM%' OR o.name LIKE '%PMA%' OR o.name LIKE '%PROD%' OR o.name LIKE '%PART%')
ORDER BY o.name;

-- ===== 3. Every code the BOM needs, parents and components together =====
-- SQL Server will not aggregate over a subquery, so every flag the grids below count
-- is worked out once here, as a column, and only then summed.
IF OBJECT_ID('tempdb..#need') IS NOT NULL DROP TABLE #need;
SELECT part, MAX(as_parent) AS as_parent, MAX(as_component) AS as_component
INTO #need
FROM (
    SELECT RTRIM(CAST(ITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part, 1 AS as_parent, 0 AS as_component
    FROM migration.vw_BOMP
    WHERE ITMREF IS NOT NULL AND RTRIM(CAST(ITMREF AS nvarchar(60))) <> ''
    UNION ALL
    SELECT RTRIM(CAST(CPNITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT, 0, 1
    FROM migration.vw_BOMP
    WHERE CPNITMREF IS NOT NULL AND RTRIM(CAST(CPNITMREF AS nvarchar(60))) <> ''
) z
GROUP BY part;

IF OBJECT_ID('tempdb..#pma') IS NOT NULL DROP TABLE #pma;
SELECT RTRIM(CAST(PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part,
       MAX(CAST(PMA_DO_NOT_USE AS int)) AS do_not_use
INTO #pma
FROM dbo.ASC_PMA_TBL
GROUP BY RTRIM(CAST(PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT;
CREATE CLUSTERED INDEX ix_pma ON #pma(part);

IF OBJECT_ID('tempdb..#flag') IS NOT NULL DROP TABLE #flag;
SELECT n.part, n.as_parent, n.as_component,
       CASE WHEN p.part IS NULL THEN 0 ELSE 1 END AS in_the_part_master,
       p.do_not_use,
       CASE WHEN s.part IS NULL THEN 0 ELSE 1 END AS holding_stock,
       CASE WHEN b.part IS NULL THEN 0 ELSE 1 END AS bought_in_last_2_years,
       CASE WHEN c.part IS NULL THEN 0 ELSE 1 END AS sold_in_last_2_years
INTO #flag
FROM #need n
LEFT JOIN #pma p ON p.part = n.part
LEFT JOIN (SELECT DISTINCT RTRIM(CAST(LOT_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part
             FROM dbo.ASC_LOT_TBL WHERE LOT_PHYSICAL > 0) s ON s.part = n.part
LEFT JOIN (SELECT DISTINCT RTRIM(CAST(POR_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part
             FROM dbo.ASC_POR_TBL WHERE POR_ORDER_DATE >= DATEADD(year, -2, GETDATE())) b ON b.part = n.part
LEFT JOIN (SELECT DISTINCT RTRIM(CAST(COR_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part
             FROM dbo.ASC_COR_TBL WHERE COR_ORDER_DATE >= DATEADD(year, -2, GETDATE())) c ON c.part = n.part;

SELECT COUNT(*) AS codes_the_bom_needs,
       SUM(as_parent) AS used_as_a_parent,
       SUM(as_component) AS used_as_a_component,
       SUM(in_the_part_master) AS in_the_part_master,
       COUNT(*) - SUM(in_the_part_master) AS not_in_the_part_master
FROM #flag;

-- ===== 4. Of the codes that ARE in the part master, what the flags say =====
SELECT do_not_use,
       COUNT(*) AS parts,
       SUM(as_parent) AS used_as_a_parent,
       SUM(as_component) AS used_as_a_component
FROM #flag
WHERE in_the_part_master = 1
GROUP BY do_not_use
ORDER BY do_not_use;

-- ===== 5. Do the ones marked do-not-use still have life in them? =====
-- If they hold stock, or have been bought or sold recently, leaving them out breaks a
-- structure that is still being used. This is the grid that decides it.
SELECT do_not_use,
       COUNT(*) AS parts,
       SUM(holding_stock) AS holding_stock,
       SUM(bought_in_last_2_years) AS bought_in_last_2_years,
       SUM(sold_in_last_2_years) AS sold_in_last_2_years,
       SUM(CASE WHEN holding_stock = 0 AND bought_in_last_2_years = 0
                 AND sold_in_last_2_years = 0 THEN 1 ELSE 0 END) AS no_sign_of_life
FROM #flag
WHERE in_the_part_master = 1
GROUP BY do_not_use
ORDER BY do_not_use;

-- ===== 6. Thirty of the busiest codes the BOM needs and the part master does not hold =====
IF OBJECT_ID('tempdb..#uses') IS NOT NULL DROP TABLE #uses;
SELECT part, SUM(n) AS bom_lines
INTO #uses
FROM (
    SELECT RTRIM(CAST(ITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part, COUNT(*) AS n
    FROM migration.vw_BOMP GROUP BY RTRIM(CAST(ITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT
    UNION ALL
    SELECT RTRIM(CAST(CPNITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT, COUNT(*)
    FROM migration.vw_BOMP GROUP BY RTRIM(CAST(CPNITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT
) z
GROUP BY part;

SELECT TOP 30 f.part, f.as_parent, f.as_component, u.bom_lines
FROM #flag f
LEFT JOIN #uses u ON u.part = f.part
WHERE f.in_the_part_master = 0
ORDER BY u.bom_lines DESC;

-- ===== 7. The ones the part master does not hold - do they show life anywhere? =====
SELECT COUNT(*) AS codes_not_in_the_part_master,
       SUM(holding_stock) AS holding_stock,
       SUM(bought_in_last_2_years) AS bought_in_last_2_years,
       SUM(sold_in_last_2_years) AS sold_in_last_2_years
FROM #flag
WHERE in_the_part_master = 0;
GO
