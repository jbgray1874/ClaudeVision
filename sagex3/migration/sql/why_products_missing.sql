-- why_products_missing.sql  -  READ ONLY, changes nothing
--
-- 8,453 parent products in the BOM load are not in the product load, and not in the
-- routing or cost files either. Either they are obsolete and rightly left out, or the
-- product extract is filtering too hard. This settles which.
-- Returns 5 grids - paste them all back (all small).
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. What the migration schema holds, so we can see which view built the product file =====
SELECT o.type_desc, s.name AS [schema], o.name AS [object],
       ISNULL((SELECT SUM(p.rows) FROM sys.partitions p
                WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)), -1) AS table_rows
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name = 'migration' AND o.type IN ('U', 'V')
ORDER BY o.name;

-- ===== 2. The flags on the part master that an extract would filter on =====
SELECT c.name AS [column], ty.name AS [type]
FROM sys.columns c
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dbo.ASC_PMA_TBL')
  AND (c.name LIKE '%DO[_]NOT[_]USE%' OR c.name LIKE '%ARCHIVE%' OR c.name LIKE '%STATUS%'
       OR c.name LIKE '%OBSOLETE%' OR c.name LIKE '%DISCONT%' OR c.name LIKE '%ACTIVE%'
       OR c.name LIKE '%SOURCE%' OR c.name LIKE '%TYPE%' OR c.name LIKE '%DATE%')
ORDER BY c.column_id;

-- ===== 3. Are the BOM parents in the part master at all? =====
IF OBJECT_ID('tempdb..#par') IS NOT NULL DROP TABLE #par;
SELECT DISTINCT RTRIM(CAST(ITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT AS part
INTO #par
FROM migration.vw_BOMP;

SELECT COUNT(*) AS bom_parents,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM dbo.ASC_PMA_TBL p
                              WHERE RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT = x.part)
                THEN 1 ELSE 0 END) AS in_the_part_master,
       SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM dbo.ASC_PMA_TBL p
                              WHERE RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT = x.part)
                THEN 1 ELSE 0 END) AS not_in_the_part_master
FROM #par x;

-- ===== 4. How many BOM parents the part master itself marks as not in use =====
SELECT CAST(p.PMA_DO_NOT_USE AS int) AS do_not_use,
       COUNT(*) AS parts
FROM dbo.ASC_PMA_TBL p
JOIN #par x ON x.part = RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT
GROUP BY CAST(p.PMA_DO_NOT_USE AS int)
ORDER BY do_not_use;

-- ===== 5. A look at 30 of them =====
SELECT TOP 30 RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) AS part,
       CAST(p.PMA_DO_NOT_USE AS int) AS do_not_use,
       CAST(p.PMA_COST_MAT AS decimal(18, 4)) AS material_cost,
       (SELECT COUNT(*) FROM migration.vw_BOMP b
         WHERE RTRIM(CAST(b.ITMREF AS nvarchar(60))) COLLATE DATABASE_DEFAULT
             = RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT) AS bom_lines
FROM dbo.ASC_PMA_TBL p
JOIN #par x ON x.part = RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60))) COLLATE DATABASE_DEFAULT
WHERE CAST(p.PMA_DO_NOT_USE AS int) = 1
ORDER BY RTRIM(CAST(p.PMA_PART_ONLY AS nvarchar(60)));
GO
