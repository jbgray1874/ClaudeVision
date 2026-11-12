/* ============================================================================
   WHAT IS IN THE PRICE TABLES — read-only.

   Every statement here is a SELECT. Nothing is inserted, updated, deleted or
   altered, and nothing in the ERP's own dbo schema is touched beyond reading it.

   Two schemas live in the SDILive database and they are not the same thing:

       SDILive.dbo.*            the ERP's own tables. Theirs. We only SELECT.
       SDILive.AIEstimating.*   our schema, written by catalogue_loader.py.

   Answers four questions:
     1  is there anything in our catalogue, and what is it made of
     2  is dbo.bought_in_parts really empty (the engine still queries it)
     3  what the historical harvest has landed, by workbook
     4  what each source says about two parts we are arguing about

   Run in SSMS against SDILive.
   ============================================================================ */

SET NOCOUNT ON;

/* -- 1a. Does our catalogue exist, and how much of it is live? -------------- */
IF OBJECT_ID('AIEstimating.BoughtInCatalogue') IS NULL
    SELECT 'AIEstimating.BoughtInCatalogue DOES NOT EXIST' AS answer;
ELSE
    SELECT
        COUNT(*)                                             AS rows_total,
        SUM(CASE WHEN effective_to IS NULL THEN 1 ELSE 0 END) AS rows_live,
        COUNT(DISTINCT source)                               AS distinct_sources,
        MIN(effective_from)                                  AS oldest,
        MAX(effective_from)                                  AS newest
    FROM AIEstimating.BoughtInCatalogue;

/* -- 1b. What is it made of? THE INTERESTING ONE. --------------------------
   source carries the tag the loader stamped: migrated:dbo.bip, supplier_file:<name>,
   rag_fallback:workbook:<job>, web_indicative:<date>, sdi_estimate:<date>,
   parallel-run:<job>. Only the first two are prices we actually pay.            */
IF OBJECT_ID('AIEstimating.BoughtInCatalogue') IS NOT NULL
    SELECT
        LEFT(source, 40)        AS source_tag,
        COUNT(*)                AS live_rows,
        MIN(effective_from)     AS oldest,
        MAX(effective_from)     AS newest,
        CAST(MIN(unit_price_gbp) AS decimal(12,2)) AS cheapest,
        CAST(MAX(unit_price_gbp) AS decimal(12,2)) AS dearest,
        SUM(CASE WHEN unit_price_gbp IS NULL OR unit_price_gbp <= 0
                 THEN 1 ELSE 0 END)                AS zero_or_null_price
    FROM AIEstimating.BoughtInCatalogue
    WHERE effective_to IS NULL
    GROUP BY LEFT(source, 40)
    ORDER BY live_rows DESC;

/* -- 2. Is dbo.bought_in_parts really empty? -------------------------------
   The engine's UDEF query still unions this table WITH is_active = 1. If
   active_rows is 0, that half of the union has been returning nothing on every
   job since the migration, and every SDI Live price comes from UDEF alone —
   which is the half the query stamps with GETDATE().                            */
IF OBJECT_ID('dbo.bought_in_parts') IS NULL
    SELECT 'dbo.bought_in_parts DOES NOT EXIST' AS answer;
ELSE
    SELECT
        COUNT(*)                                          AS rows_total,
        SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END)     AS active_rows,
        SUM(CASE WHEN effective_date IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_a_date
    FROM dbo.bought_in_parts;

/* -- 3. What has the historical harvest actually landed? -------------------
   JobBoughtInMaterials is the raw per-job provenance: one row per bought-in
   line per drawing, with the workbook it came out of.                           */
IF OBJECT_ID('AIEstimating.JobBoughtInMaterials') IS NULL
    SELECT 'AIEstimating.JobBoughtInMaterials DOES NOT EXIST' AS answer;
ELSE
BEGIN
    SELECT
        COUNT(*)                        AS rows_total,
        COUNT(DISTINCT drawing_number)  AS drawings,
        COUNT(DISTINCT source_workbook) AS workbooks,
        COUNT(DISTINCT supplier)        AS suppliers
    FROM AIEstimating.JobBoughtInMaterials;

    /* the ten most recently landed workbooks — tells you when the last ingest ran */
    SELECT TOP (10)
        source_workbook,
        COUNT(*)                                    AS lines,
        COUNT(DISTINCT drawing_number)              AS drawings,
        CAST(SUM(total_gbp) AS decimal(12,2))       AS total_gbp
    FROM AIEstimating.JobBoughtInMaterials
    GROUP BY source_workbook
    ORDER BY lines DESC;
END

/* -- 4. What does each source say about the parts we are arguing about? ----
   TAPE113C   Howard states £4.50 a 10 m roll; we hold that as an estimator
              figure because nothing priced it.
   PLAS534    Howard says the supplier is at £45.19 a sheet, our sheet charged
              £47.21, and he believes the system's £49.55 was migrated from the
              old system. Three numbers, one board.                              */
DECLARE @codes TABLE (code nvarchar(60));
INSERT INTO @codes(code) VALUES (N'TAPE113C'), (N'PLAS534');

IF OBJECT_ID('dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING') IS NOT NULL
    SELECT
        'UDEF'                          AS source,
        u.[Part code]                   AS part_code,
        u.[Description]                 AS description,
        u.[Supplier name]               AS supplier,
        u.[UOM]                         AS uom,
        CAST(u.[System cost per] AS decimal(12,4)) AS price_gbp,
        NULL                            AS effective_from
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE EXISTS (SELECT 1 FROM @codes c
                  WHERE LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = c.code
                     OR u.[Description] COLLATE Latin1_General_CI_AS LIKE '%' + c.code + '%');

IF OBJECT_ID('AIEstimating.BoughtInCatalogue') IS NOT NULL
    SELECT
        'AIEstimating'                  AS source,
        b.supplier_sku                  AS part_code,
        b.description,
        s.name                          AS supplier,
        b.uom,
        CAST(b.unit_price_gbp AS decimal(12,4)) AS price_gbp,
        b.effective_from,
        b.source                        AS source_tag,
        b.version
    FROM AIEstimating.BoughtInCatalogue b
    LEFT JOIN AIEstimating.Supplier s ON s.supplier_id = b.supplier_id
    WHERE b.effective_to IS NULL
      AND EXISTS (SELECT 1 FROM @codes c
                  WHERE LTRIM(RTRIM(b.supplier_sku)) = c.code
                     OR b.description LIKE '%' + c.code + '%');
