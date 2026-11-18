-- products_by_supplier_country.sql  -  READ ONLY, changes nothing.  Run against SDILive.
--
-- Jim (Acuity), 18 Nov: "would the same single Product not potentially be shared across those
-- 3 'routes'?" (UK / Poland / Chinese sub-contract). This answers it from the purchase orders:
-- for every product bought in the last 24 months, which supplier countries it was bought from.
--
-- Supplier country = PL_ACCOUNTS.SU_COUNTRY_CODE; blank is taken as GB.
--
-- Grids:
--   SUMMARY   products by how many supplier countries they were bought from (1, 2, 3+), and by the
--             mix of countries - if almost every product has one country, a product-level
--             route works; if many have several, the route belongs on the purchase, not the product
--   SHARED    every product bought from more than one country: countries, suppliers, PO lines,
--             value, last order
-- (FOR XML PATH, not STRING_AGG, so it runs whatever the database compatibility level.)

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#b') IS NOT NULL DROP TABLE #b;

SELECT UPPER(LTRIM(RTRIM(p.POR_PART_ONLY))) COLLATE DATABASE_DEFAULT                  AS part,
       LTRIM(RTRIM(p.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT                          AS supplier,
       COALESCE(NULLIF(UPPER(LTRIM(RTRIM(a.SU_COUNTRY_CODE))), ''), 'GB') COLLATE DATABASE_DEFAULT AS country,
       p.POR_ORDER_DATE                                                               AS order_date,
       CAST(ISNULL(p.POR_QTY_ORDERED, 0) * ISNULL(p.POR_UOP_PRICE, 0)
            / NULLIF(CAST(NULLIF(p.POR_UOP_PRICE_PER, 0) AS decimal(18, 6)), 0) AS decimal(18, 2)) AS value_gbp
INTO #b
FROM dbo.ASC_POR_TBL p
LEFT JOIN dbo.PL_ACCOUNTS a
       ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(p.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT
WHERE p.POR_ORDER_DATE >= DATEADD(month, -24, GETDATE())
  AND LTRIM(RTRIM(ISNULL(p.POR_PART_ONLY, ''))) <> '';

IF OBJECT_ID('tempdb..#pc') IS NOT NULL DROP TABLE #pc;
SELECT d.part, COUNT(*) AS countries,
       STUFF((SELECT '/' + c.country FROM (SELECT DISTINCT country FROM #b WHERE part = d.part) c
              ORDER BY c.country FOR XML PATH('')), 1, 1, '') AS mix
INTO #pc
FROM (SELECT DISTINCT part, country FROM #b) d
GROUP BY d.part;

SELECT 'SUMMARY' AS grid,
       CASE WHEN countries >= 3 THEN '3+' ELSE CAST(countries AS varchar(2)) END AS countries,
       mix, COUNT(*) AS products
FROM #pc
GROUP BY CASE WHEN countries >= 3 THEN '3+' ELSE CAST(countries AS varchar(2)) END, mix
ORDER BY 2, 4 DESC;

SELECT 'SHARED' AS grid, b.part, pc.mix AS countries,
       STUFF((SELECT '/' + s.supplier FROM (SELECT DISTINCT supplier FROM #b WHERE part = b.part) s
              ORDER BY s.supplier FOR XML PATH('')), 1, 1, '') AS suppliers,
       COUNT(*) AS po_lines, SUM(b.value_gbp) AS value_gbp,
       CONVERT(varchar(10), MAX(b.order_date), 23) AS last_order
FROM #b b
JOIN #pc pc ON pc.part = b.part AND pc.countries > 1
GROUP BY b.part, pc.mix
ORDER BY value_gbp DESC;
