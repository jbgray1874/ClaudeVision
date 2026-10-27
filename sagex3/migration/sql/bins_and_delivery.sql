-- bins_and_delivery.sql  -  READ ONLY, changes nothing
--
-- Two things Marc's answers opened up.
--
-- 1. BINS. Marc will send the X3 location codes for us to map to. To map them we need
--    the Access bins with their warehouse beside them, because S01A is now the only site
--    and the same bin name can exist in more than one Access warehouse.
--
-- 2. DELIVERY ADDRESSES. Marc can add a ship-to column to YA004SOH. To fill it we need to
--    know where Access keeps the delivery address for an order or an order line, and how
--    that ties to the address codes in the customer load (TES101 has 001 to 1399). I have
--    not seen those columns, so this finds them rather than guessing, and then shows them
--    for the Tesco bedding order 10015257 - the one going to 50 stores.
--
-- Run views_v2.sql first if the _V2 views are not there. Seven grids.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- ===== 1. Every Access bin holding stock, by warehouse - the list to map to X3 =====
SELECT REF_WAREHOUSE                        AS access_warehouse,
       CASE WHEN LOC = '' THEN '(no bin)' ELSE LOC END AS access_bin,
       COUNT(*)                             AS lots,
       COUNT(DISTINCT ITMREF)               AS products,
       CAST(SUM(QTYSTU) AS decimal(18, 2))  AS quantity,
       CAST(SUM(REF_LOT_VALUE) AS decimal(18, 2)) AS stock_value
FROM migration.vw_SMR_V2
GROUP BY REF_WAREHOUSE, CASE WHEN LOC = '' THEN '(no bin)' ELSE LOC END
ORDER BY REF_WAREHOUSE, access_bin;

-- ===== 2. Columns on the order tables that could hold a delivery address =====
SELECT OBJECT_NAME(c.object_id) AS [table], c.column_id, c.name AS [column],
       ty.name AS [type], c.max_length
FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id IN (OBJECT_ID('dbo.ASC_COR_TBL'), OBJECT_ID('dbo.ASC_COH_TBL'))
  AND (c.name LIKE '%ADD%' OR c.name LIKE '%DEL%' OR c.name LIKE '%SHIP%'
       OR c.name LIKE '%DEST%' OR c.name LIKE '%DROP%' OR c.name LIKE '%SITE%'
       OR c.name LIKE '%STORE%' OR c.name LIKE '%BRANCH%' OR c.name LIKE '%POST%')
ORDER BY 1, 2;

-- ===== 3. The customer address table =====
SELECT c.column_id, c.name AS [column], ty.name AS [type], c.max_length
FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dbo.SL_ADDRESSES')
ORDER BY c.column_id;

SELECT TOP 5 * FROM dbo.SL_ADDRESSES;

-- ===== 4. How the customer load numbered its addresses (001, 002 ... 1399) =====
SELECT o.name AS [object], OBJECT_DEFINITION(o.object_id) AS [definition]
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name = 'migration' AND o.name IN ('vw_BPC', 'vw_DQ_BPC');

-- ===== 5. The Tesco bedding order, with every address-like column the order has =====
-- Built from grid 2's column list, so it names only columns that exist.
DECLARE @cols nvarchar(max), @sql nvarchar(max);
SELECT @cols = STUFF((
    SELECT ', CAST(' + QUOTENAME(c.name) + ' AS nvarchar(100)) AS ' + QUOTENAME(c.name)
    FROM sys.columns c
    WHERE c.object_id = OBJECT_ID('dbo.ASC_COR_TBL')
  AND (c.name LIKE '%ADD%' OR c.name LIKE '%DEL%' OR c.name LIKE '%SHIP%'
       OR c.name LIKE '%DEST%' OR c.name LIKE '%DROP%' OR c.name LIKE '%SITE%'
       OR c.name LIKE '%STORE%' OR c.name LIKE '%BRANCH%' OR c.name LIKE '%POST%')
    ORDER BY c.column_id
    FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');
SET @sql = N'SELECT TOP 60 RTRIM(COR_OUR_NUMBER) AS order_no, COR_LINE_NUM, '
         + N'RTRIM(COR_PART_ONLY) AS part, CAST(COR_QTY_ORDERED AS decimal(18,2)) AS qty'
         + ISNULL(N', ' + @cols, N'')
         + N' FROM dbo.ASC_COR_TBL WHERE RTRIM(COR_OUR_NUMBER) LIKE ''%10015257'''
         + N' ORDER BY COR_LINE_NUM';
EXEC sp_executesql @sql;

-- ===== 6. The same for the order header =====
SELECT @cols = STUFF((
    SELECT ', CAST(' + QUOTENAME(c.name) + ' AS nvarchar(100)) AS ' + QUOTENAME(c.name)
    FROM sys.columns c
    WHERE c.object_id = OBJECT_ID('dbo.ASC_COH_TBL')
  AND (c.name LIKE '%ADD%' OR c.name LIKE '%DEL%' OR c.name LIKE '%SHIP%'
       OR c.name LIKE '%DEST%' OR c.name LIKE '%DROP%' OR c.name LIKE '%SITE%'
       OR c.name LIKE '%STORE%' OR c.name LIKE '%BRANCH%' OR c.name LIKE '%POST%'
       OR c.name LIKE '%NUMBER%' OR c.name LIKE '%CUST%')
    ORDER BY c.column_id
    FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');
IF @cols IS NOT NULL
BEGIN
    SET @sql = N'SELECT TOP 5 ' + @cols
             + N' FROM dbo.ASC_COH_TBL WHERE RTRIM(COH_OUR_NUMBER) LIKE ''%10015257''';
    EXEC sp_executesql @sql;
END
GO
