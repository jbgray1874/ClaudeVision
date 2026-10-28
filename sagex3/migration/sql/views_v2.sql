-- views_v2.sql
--
-- The five transactional views rewritten against the templates Marc and Ethan issued.
--
-- These are created as _V2 alongside the originals rather than over the top of them, so
-- nothing existing is destroyed and the two can be compared. When you are happy, the
-- swap is a rename - the statements for that are at the foot of this file, commented out.
--
-- What changed, in short:
--   * every column the template asks for, in the template's order, with its own name
--   * S01A everywhere, not SITE01
--   * dates as YYYYMMDD (style 112), not DD/MM/YYYY
--   * one fixed accounting date, in one place, used by all five
--   * real prices instead of price-per divisors and line values
--   * the sterling currency code mapped from the Access '£' to 'GBP'
--   * the foreign-currency amount tested on its value, not on NULL, because Access
--     writes zero rather than null on sterling rows
--   * stock read from the lot table, so warehouses, bins and supplier lots survive
--   * duplicate document references given a suffix, since both templates reject them
--   * nothing silently dropped: the archive flag and the Access order number and
--     warehouse are carried as trailing reference columns, so the decision to exclude
--     is taken in the open and not buried in a WHERE clause
--
-- The trailing columns are named REF_* and are NOT part of the template. The file build
-- drops them after using them to group, filter and check.
--
-- Two things these views deliberately do NOT do:
--   1. Nothing. Customer, supplier and product codes all come out as the SAGE codes.
--      Run xref_sage_codes.sql FIRST - it builds migration.XREF_SAGE_BPC and
--      XREF_SAGE_BPS, which these views join to. Note that migration.XREF_BPC and
--      XREF_BPS hold a numbering (CUS1001, SUP1001) that was never used; the codes
--      actually loaded are derived from the name - VIS500, HAF500, ABW100.
--   2. No warehouse is excluded. That is Marc's call, and REF_WAREHOUSE is there for it.
USE SDILive;
GO
SET NOCOUNT ON;
GO

-- ===========================================================================
--  The accounting date. One value, used by all five. Change it in ONE place.
--     UAT      20261031
--     Go-live  20261231   (31 December 2026 - the go-live run, James 28 Oct)
--  A view cannot take a parameter, so it is a literal in each one below and the
--  comment -- ACCOUNTING DATE marks every occurrence.
-- ===========================================================================

-- ===========================================================================
--  A lookup built once, so the views do not have to cleanse 41,898 stock codes
--  for every row they return. Without it the script crawls: the cleansing
--  expression cannot use an index, so every order line rescans the stock table.
--
--  It is also where the blank descriptions are finally answered. Of the 1,351
--  products on open sales orders, all 1,351 are in STK_STOCK - but only 694 have
--  anything in STKNAME. The real description is in ITMDES3, which comes from
--  PMA_DESC_3: where STKNAME is empty, ITMDES3 reads "GOALPOST 10083-00-GA3",
--  "SIDE GRAPHIC HOLDER", "HOOK BRACKET".
--
--  So the description is taken from migration.LOAD_ITM, which is what actually went
--  into X3, trying ITMDES1 then ITMDES3 then ITMDES2, and falling back to STKNAME for
--  the products LOAD_ITM does not hold. LOAD_ITM.ITMREF is the RAW Access code, so
--  both sides are cleansed here, once.
--
--  Units are not taken from vw_ITM because vw_ITM hardcodes them: STU, PUU and SAU
--  are all 'EA' in its own definition. The order's own unit is used where it has
--  one, 'EA' otherwise.
-- ===========================================================================
IF OBJECT_ID('migration.ITM_LOOKUP') IS NOT NULL DROP TABLE migration.ITM_LOOKUP;
WITH src AS (
    SELECT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(i.ITMREF)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT                       AS code,
           LEFT(COALESCE(NULLIF(LTRIM(RTRIM(ISNULL(i.ITMDES1, ''))), ''),
                         NULLIF(LTRIM(RTRIM(ISNULL(i.ITMDES3, ''))), ''),
                         NULLIF(LTRIM(RTRIM(ISNULL(i.ITMDES2, ''))), ''), ''), 30)
               COLLATE DATABASE_DEFAULT                       AS ITMDES,
           0                                                  AS pri
    FROM migration.LOAD_ITM i
    WHERE LTRIM(RTRIM(ISNULL(i.ITMREF, ''))) <> ''
    UNION ALL
    SELECT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(k.STKCODE)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT,
           LEFT(LTRIM(RTRIM(ISNULL(k.STKNAME, ''))), 30) COLLATE DATABASE_DEFAULT,
           1
    FROM dbo.STK_STOCK k
    WHERE LTRIM(RTRIM(ISNULL(k.STKCODE, ''))) <> ''
), ranked AS (
    -- a description that says something beats one that does not, and the item load
    -- beats the stock master where both have one
    SELECT code, ITMDES, pri,
           ROW_NUMBER() OVER (PARTITION BY code
                              ORDER BY CASE WHEN ITMDES = '' THEN 1 ELSE 0 END, pri) AS rn
    FROM src
)
SELECT code, ITMDES, pri AS from_item_load
INTO   migration.ITM_LOOKUP
FROM   ranked
WHERE  rn = 1;
CREATE UNIQUE CLUSTERED INDEX ix_itm_lookup ON migration.ITM_LOOKUP(code);
GO

-- ===========================================================================
--  1. vw_SOH_V2   open sales orders
-- ===========================================================================
CREATE OR ALTER VIEW migration.vw_SOH_V2 AS
WITH src AS (
    SELECT c.*,
           UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(c.COR_PART_ONLY)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT AS ITMREF_KEY,
           ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(c.COR_OUR_NUMBER))
                              ORDER BY c.COR_LINE_NUM, c.COR_PART_ONLY) AS line_seq
    FROM dbo.ASC_COR_TBL c
    WHERE c.COR_QTY_ORDERED - ISNULL(c.COR_QTY_DELIVERED, 0) > 0
      AND ISNULL(c.COR_ORDER_STATUS, '') IN ('', 'B', 'H')   -- C is completed: 25,975 lines, 31 outstanding
      AND LTRIM(RTRIM(ISNULL(c.COR_PART_ONLY, ''))) <> ''
      AND LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_CODE, ''))) <> ''
)
SELECT
    'S01A'                                                      AS SALFCY,
    'SON'                                                       AS SOHTYP,
    ''                                                          AS SOHNUM,
    xc.SAGE_CODE                                                AS BPCORD,
    CONVERT(varchar(8), s.COR_ORDER_DATE, 112)                  AS ORDDAT,
    CONVERT(varchar(8),
            CASE WHEN s.COR_CUSTOMER_DUE  > '19000102' THEN s.COR_CUSTOMER_DUE
                 WHEN s.COR_EXPECTED_DATE > '19000102' THEN s.COR_EXPECTED_DATE
                 ELSE s.COR_ORDER_DATE END, 112)                AS DEMDLVDAT,
    LTRIM(RTRIM(ISNULL(s.COR_CUSTOMER_ORDER, ''))) COLLATE DATABASE_DEFAULT              AS CUSORDREF,
    'S01A'                                                      AS STOFCY,
    CONVERT(varchar(8),
            CASE WHEN s.COR_EXPECTED_DATE > '19000102' THEN s.COR_EXPECTED_DATE
                 WHEN s.COR_CUSTOMER_DUE  > '19000102' THEN s.COR_CUSTOMER_DUE
                 ELSE s.COR_ORDER_DATE END, 112)                AS SHIDAT,
    ''                                                          AS BPTNUM,
    0                                                           AS [INVDTAAMT(0)],
    CASE WHEN LTRIM(RTRIM(ISNULL(s.COR_CURRENCY, ''))) IN ('EUR', 'USD')
         THEN LTRIM(RTRIM(s.COR_CURRENCY)) COLLATE DATABASE_DEFAULT ELSE 'GBP' END       AS CUR,
    ''                                                          AS [*71],
    s.line_seq * 1000                                           AS SOPLIN,
    s.ITMREF_KEY                                                AS ITMREF,
    ISNULL(i.ITMDES, '')                                        AS ITMDES,
    COALESCE(NULLIF(LTRIM(RTRIM(s.COR_UOM_ENTERED)), ''), 'EA')
         COLLATE DATABASE_DEFAULT
                                                                AS SAU,
    CAST(s.COR_QTY_ORDERED - ISNULL(s.COR_QTY_DELIVERED, 0) AS decimal(18, 5))
                                                                AS QTY,
    -- the discounted price is what the order is actually worth; the template has no
    -- discount column, so loading the gross price would overstate every discounted line
    CAST(COALESCE(
            CASE WHEN ISNULL(s.COR_DISC_PRICE, 0) <> 0
                 THEN s.COR_DISC_PRICE / NULLIF(CAST(s.COR_DISC_PRICE_PER AS decimal(18, 6)), 0) END,
            CASE WHEN ISNULL(s.COR_ORIG_PRICE, 0) <> 0
                 THEN s.COR_ORIG_PRICE / NULLIF(CAST(s.COR_ORIG_PRICE_PER AS decimal(18, 6)), 0) END,
            0) AS decimal(18, 5))                               AS GROPRI,
    ''                                                          AS [*91],
    -- reference only, dropped by the file build
    LTRIM(RTRIM(s.COR_OUR_NUMBER)) COLLATE DATABASE_DEFAULT     AS REF_ORDER_NUMBER,
    LTRIM(RTRIM(s.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT  AS REF_ACCESS_CUSTOMER,
    ISNULL(s.COR_ORDER_STATUS, '')                              AS REF_ORDER_STATUS,
    CASE WHEN ISNULL(s.COR_DISC_PRICE, 0) = 0
          AND ISNULL(s.COR_ORIG_PRICE, 0) = 0 THEN 1 ELSE 0 END AS REF_NO_PRICE
FROM src s
LEFT JOIN migration.ITM_LOOKUP i
       ON i.code = s.ITMREF_KEY
-- INNER join: a line whose customer has no Sage account has nowhere to go, and a row
-- with a blank customer would be rejected by X3 anyway. The count is checked below.
JOIN migration.XREF_SAGE_BPC xc
       ON xc.ACCESS_CODE = LTRIM(RTRIM(s.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT;
GO

-- ===========================================================================
--  2. vw_POH_V2   open purchase orders
-- ===========================================================================
CREATE OR ALTER VIEW migration.vw_POH_V2 AS
WITH src AS (
    SELECT p.*,
           UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(p.POR_PART_ONLY)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT AS ITMREF_KEY,
           ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(p.POR_NUMBER))
                              ORDER BY p.POR_LINE_NO, p.POR_PART_ONLY) AS line_seq
    FROM dbo.ASC_POR_TBL p
    WHERE p.POR_QTY_ORDERED - ISNULL(p.POR_QTY_DELIVERED, 0) - ISNULL(p.POR_QTY_REJECTED, 0) > 0
      AND LTRIM(RTRIM(ISNULL(p.POR_PART_ONLY, ''))) <> ''
      AND LTRIM(RTRIM(ISNULL(p.POR_SUP_CODE, ''))) <> ''
)
SELECT
    'S01A'                                                      AS POHFCY,
    ''                                                          AS POHNUM,
    CONVERT(varchar(8), s.POR_ORDER_DATE, 112)                  AS ORDDAT,
    xs.SAGE_CODE                                                AS BPSNUM,
    CASE WHEN LTRIM(RTRIM(ISNULL(s.POR_CURR_CODE, ''))) IN ('EUR', 'USD')
         THEN LTRIM(RTRIM(s.POR_CURR_CODE)) COLLATE DATABASE_DEFAULT ELSE 'GBP' END      AS CUR,
    ''                                                          AS [*71],
    s.line_seq * 1000                                           AS POPLIN,
    s.ITMREF_KEY                                                AS ITMREF,
    ISNULL(i.ITMDES, '')                                        AS ITMDES,
    'S01A'                                                      AS PRHFCY,
    COALESCE(NULLIF(LTRIM(RTRIM(s.POR_UOM)), ''), 'EA')
         COLLATE DATABASE_DEFAULT
                                                                AS UOM,
    CAST(s.POR_QTY_ORDERED - ISNULL(s.POR_QTY_DELIVERED, 0) - ISNULL(s.POR_QTY_REJECTED, 0)
         AS decimal(18, 5))                                     AS QTYUOM,
    CONVERT(varchar(8),
            CASE WHEN s.POR_LATEST_DUE_DATE > '19000102' THEN s.POR_LATEST_DUE_DATE
                 WHEN s.POR_DUE_DATE        > '19000102' THEN s.POR_DUE_DATE
                 ELSE s.POR_ORDER_DATE END, 112)                AS EXTRCPDAT,
    -- the price must be in the order's own currency: the unit-of-purchase price for
    -- sterling, the foreign price where the order is not in sterling
    CAST(CASE WHEN LTRIM(RTRIM(ISNULL(s.POR_CURR_CODE, ''))) IN ('EUR', 'USD')
                   AND ISNULL(s.POR_FORN_PRICE, 0) <> 0
              THEN s.POR_FORN_PRICE
              ELSE ISNULL(s.POR_UOP_PRICE, 0)
                   / NULLIF(CAST(NULLIF(s.POR_UOP_PRICE_PER, 0) AS decimal(18, 6)), 0)
         END AS decimal(18, 5))                                 AS GROPRI,
    ''                                                          AS [*91],
    -- reference only
    LTRIM(RTRIM(s.POR_NUMBER)) COLLATE DATABASE_DEFAULT         AS REF_ORDER_NUMBER,
    LTRIM(RTRIM(s.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT       AS REF_ACCESS_SUPPLIER,
    LTRIM(RTRIM(ISNULL(s.POR_SUP_REF, ''))) COLLATE DATABASE_DEFAULT                     AS REF_SUPPLIER_REF,
    CASE WHEN ISNULL(s.POR_UOP_PRICE, 0) = 0
          AND ISNULL(s.POR_FORN_PRICE, 0) = 0 THEN 1 ELSE 0 END AS REF_NO_PRICE
FROM src s
LEFT JOIN migration.ITM_LOOKUP i
       ON i.code = s.ITMREF_KEY
JOIN migration.XREF_SAGE_BPS xs
       ON xs.ACCESS_CODE = LTRIM(RTRIM(s.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT;
GO

-- ===========================================================================
--  3. vw_SMR_V2   opening stock, from the lot table
-- ===========================================================================
CREATE OR ALTER VIEW migration.vw_SMR_V2 AS
SELECT
    '19'                                                        AS VCRTYP,
    ''                                                          AS VCRNUM,
    'S01A'                                                      AS STOFCY,
    '20261031'                                                  AS IPTDAT,   -- ACCOUNTING DATE
    'OPENING STOCK'                                             AS VCRDES,
    ''                                                          AS TRSCOD,
    ROW_NUMBER() OVER (ORDER BY l.LOT_PART_ONLY, l.LOT_WH, l.LOT_NUM, l.LOT_SUB)
                                                                AS VCRLIN,
    UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        REPLACE(LTRIM(RTRIM(l.LOT_PART_ONLY)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
                                                                AS ITMREF,
    COALESCE(NULLIF(LTRIM(RTRIM(p.PMA_UOM)), ''), 'EA')
         COLLATE DATABASE_DEFAULT
                                                                AS PCU,
    CAST(l.LOT_PHYSICAL AS decimal(18, 5))                      AS QTYPCU,
    COALESCE(NULLIF(LTRIM(RTRIM(p.PMA_UOM)), ''), 'EA')
         COLLATE DATABASE_DEFAULT
                                                                AS STU,
    CAST(l.LOT_PHYSICAL AS decimal(18, 5))                      AS QTYSTU,
    -- the lot's full cost. Material alone is £3,997,506.56; with labour it is
    -- £4,011,655.63, and that is the figure the opening stock has to tie to
    CAST(ISNULL(l.LOT_COST_EACH, 0) + ISNULL(l.LOT_LAB_COST_EACH, 0)
       + ISNULL(l.LOT_OHD_COST_EA, 0) + ISNULL(l.LOT_OTHER_COST_EA, 0)
         AS decimal(18, 5))                                     AS PRI,
    COALESCE(NULLIF(LTRIM(RTRIM(p.PMA_UOM)), ''), 'EA')
         COLLATE DATABASE_DEFAULT
                                                                AS PCU2,
    CAST(l.LOT_PHYSICAL AS decimal(18, 5))                      AS QTYPCU2,
    LEFT(LTRIM(RTRIM(ISNULL(l.LOT_SUPP_REF, ''))), 20) COLLATE DATABASE_DEFAULT          AS BPSLOT,
    ''                                                          AS LOT,
    LTRIM(RTRIM(ISNULL(l.LOT_BIN_ONLY, ''))) COLLATE DATABASE_DEFAULT                    AS LOC,
    'A'                                                         AS STA,
    -- reference only: the warehouse decision is Marc's, so it is exposed, not buried
    LTRIM(RTRIM(ISNULL(l.LOT_WH, ''))) COLLATE DATABASE_DEFAULT                          AS REF_WAREHOUSE,
    CAST(l.LOT_PHYSICAL * (ISNULL(l.LOT_COST_EACH, 0) + ISNULL(l.LOT_LAB_COST_EACH, 0)
       + ISNULL(l.LOT_OHD_COST_EA, 0) + ISNULL(l.LOT_OTHER_COST_EA, 0))
         AS decimal(18, 2))                                     AS REF_LOT_VALUE,
    CASE WHEN LTRIM(RTRIM(ISNULL(l.LOT_BIN_ONLY, ''))) COLLATE DATABASE_DEFAULT = '' THEN 1 ELSE 0 END
                                                                AS REF_NO_BIN
FROM dbo.ASC_LOT_TBL l
LEFT JOIN dbo.ASC_PMA_TBL p
       ON p.PMA_PART_ONLY COLLATE DATABASE_DEFAULT = l.LOT_PART_ONLY COLLATE DATABASE_DEFAULT
WHERE l.LOT_PHYSICAL > 0;
GO

-- ===========================================================================
--  4. vw_BICX_V2   customer open items
-- ===========================================================================
CREATE OR ALTER VIEW migration.vw_BICX_V2 AS
WITH src AS (
    SELECT t.*,
           ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(t.ST_HEADER_REF))
                              ORDER BY t.ST_DATE, t.ST_PRIMARY) AS ref_seq
    FROM dbo.SL_TRANSACTIONS t
    WHERE t.ST_UNALLOCATED <> 0
      AND LTRIM(RTRIM(ISNULL(t.ST_COPYCUST, ''))) <> ''
)
SELECT
    CASE LTRIM(RTRIM(s.ST_TRANTYPE))
         WHEN 'INV' THEN 'MINV'
         WHEN 'CRN' THEN 'MCRN'
         WHEN 'PAY' THEN 'MREC'
         WHEN 'ADR' THEN 'MJDT'
         WHEN 'ACR' THEN 'MJCT'
         ELSE 'MINV' END                                        AS InvoiceType,
    -- 13 references repeat (BACS, FP). The template rejects duplicates, so the second
    -- and later ones take a suffix, the same way Ethan's own examples do
    CASE WHEN s.ref_seq = 1 THEN LTRIM(RTRIM(s.ST_HEADER_REF)) COLLATE DATABASE_DEFAULT
         ELSE LEFT(LTRIM(RTRIM(s.ST_HEADER_REF)), 18) COLLATE DATABASE_DEFAULT
              + '-' + CAST(s.ref_seq AS varchar(4))
    END                                                         AS Document,
    xc.SAGE_CODE                                                AS Customer,
    'S01A'                                                      AS Site,
    '20261031'                                                  AS AccountingDate,  -- ACCOUNTING DATE
    CASE WHEN LTRIM(RTRIM(ISNULL(s.ST_CURRENCYCODE, ''))) IN ('EUR', 'USD')
         THEN LTRIM(RTRIM(s.ST_CURRENCYCODE)) COLLATE DATABASE_DEFAULT ELSE 'GBP' END    AS Currency,
    CAST(ABS(s.ST_UNALLOCATED) AS decimal(18, 2))               AS GBPAmount,
    -- Access writes ZERO, not null, in the currency column on sterling rows, so the
    -- test has to be on the value. ISNULL here would load 752 items at nil
    CAST(CASE WHEN LTRIM(RTRIM(ISNULL(s.ST_CURRENCYCODE, ''))) IN ('EUR', 'USD')
                   AND ISNULL(s.ST_CURR_UNAL, 0) <> 0
              THEN ABS(s.ST_CURR_UNAL)
              ELSE ABS(s.ST_UNALLOCATED) END AS decimal(18, 2)) AS TransactionAmount,
    CONVERT(varchar(8), s.ST_DATE, 112)                         AS SourceDate,
    xc.SAGE_CODE                                                AS PayingCustomer,
    CONVERT(varchar(8),
            CASE WHEN s.ST_DUEDATE > '19000102' THEN s.ST_DUEDATE ELSE s.ST_DATE END, 112)
                                                                AS DueDate,
    'BAC_IMM'                                                   AS PaymentTerms,
    LEFT(LTRIM(RTRIM(ISNULL(CAST(s.ST_ORDER_NUMBER AS varchar(25)), ''))), 20)
                                                                AS SourceDocument,
    LEFT(LTRIM(RTRIM(ISNULL(s.ST_DESCRIPTION, ''))), 30) COLLATE DATABASE_DEFAULT        AS Comments1,
    ''                                                          AS Comments2,
    ''                                                          AS Comments3,
    1                                                           AS Line,
    'S01A'                                                      AS LineSite,
    '18L'                                                       AS PlanCode,
    '999100'                                                    AS GeneralAccounts,
    ''                                                          AS Distribution,
    LEFT(LTRIM(RTRIM(ISNULL(s.ST_DESCRIPTION, ''))), 30) COLLATE DATABASE_DEFAULT        AS LineComment,
    CAST(CASE WHEN LTRIM(RTRIM(ISNULL(s.ST_CURRENCYCODE, ''))) IN ('EUR', 'USD')
                   AND ISNULL(s.ST_CURR_UNAL, 0) <> 0
              THEN ABS(s.ST_CURR_UNAL)
              ELSE ABS(s.ST_UNALLOCATED) END AS decimal(18, 2)) AS LineTransactionAmount,
    -- reference only. The old view excluded archived rows, which dropped 126 open items
    -- worth real money. Exposed instead, so finance decides rather than a WHERE clause
    CAST(ISNULL(s.ST_ARCHIVE_FLAG, 0) AS int)                   AS REF_ARCHIVED,
    LTRIM(RTRIM(s.ST_TRANTYPE))                                 AS REF_ACCESS_TYPE,
    CONVERT(varchar(8), s.ST_DATE, 112)                         AS REF_TRAN_DATE,
    LTRIM(RTRIM(s.ST_COPYCUST)) COLLATE DATABASE_DEFAULT        AS REF_ACCESS_CUSTOMER
FROM src s
JOIN migration.XREF_SAGE_BPC xc
       ON xc.ACCESS_CODE = LTRIM(RTRIM(s.ST_COPYCUST)) COLLATE DATABASE_DEFAULT;
GO

-- ===========================================================================
--  5. vw_BISX_V2   supplier open items
-- ===========================================================================
CREATE OR ALTER VIEW migration.vw_BISX_V2 AS
WITH src AS (
    SELECT t.*,
           ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(t.PT_HEADER_REF))
                              ORDER BY t.PT_DATE, t.PT_PRIMARY) AS ref_seq
    FROM dbo.PL_TRANSACTIONS t
    WHERE t.PT_UNALLOCATED <> 0
      AND LTRIM(RTRIM(ISNULL(t.PT_COPYSUPP, ''))) <> ''
)
SELECT
    CASE LTRIM(RTRIM(s.PT_TRANTYPE))
         WHEN 'INV' THEN 'MINV'
         WHEN 'CRN' THEN 'MCRN'
         WHEN 'PAY' THEN 'MPAY'
         WHEN 'ADR' THEN 'MJDT'
         WHEN 'ACR' THEN 'MJCT'
         ELSE 'MINV' END                                        AS InvoiceType,
    CASE WHEN s.ref_seq = 1 THEN LTRIM(RTRIM(s.PT_HEADER_REF)) COLLATE DATABASE_DEFAULT
         ELSE LEFT(LTRIM(RTRIM(s.PT_HEADER_REF)), 18) COLLATE DATABASE_DEFAULT
              + '-' + CAST(s.ref_seq AS varchar(4))
    END                                                         AS Document,
    xs.SAGE_CODE                                                AS Supplier,
    'S01A'                                                      AS Site,
    '20261031'                                                  AS AccountingDate,  -- ACCOUNTING DATE
    CASE WHEN LTRIM(RTRIM(ISNULL(s.PT_CURRENCYCODE, ''))) IN ('EUR', 'USD')
         THEN LTRIM(RTRIM(s.PT_CURRENCYCODE)) COLLATE DATABASE_DEFAULT ELSE 'GBP' END    AS Currency,
    'GBP'                                                       AS CURLED,
    CAST(ABS(s.PT_UNALLOCATED) AS decimal(18, 2))               AS GBPAmount,
    CAST(CASE WHEN LTRIM(RTRIM(ISNULL(s.PT_CURRENCYCODE, ''))) IN ('EUR', 'USD')
                   AND ISNULL(s.PT_CURR_UNAL, 0) <> 0
              THEN ABS(s.PT_CURR_UNAL)
              ELSE ABS(s.PT_UNALLOCATED) END AS decimal(18, 2)) AS TransactionAmount,
    CONVERT(varchar(8), s.PT_DATE, 112)                         AS SourceDate,
    xs.SAGE_CODE                                                AS PayingSupplier,
    CONVERT(varchar(8),
            CASE WHEN s.PT_DUEDATE > '19000102' THEN s.PT_DUEDATE ELSE s.PT_DATE END, 112)
                                                                AS DueDate,
    -- the guide says domestic versus non-domestic, which is a country test. The supplier
    -- account carries the country; currency is only the fallback where it is blank
    CASE WHEN LTRIM(RTRIM(ISNULL(a.SU_COUNTRY_CODE, ''))) <> ''
         THEN CASE WHEN LTRIM(RTRIM(a.SU_COUNTRY_CODE)) COLLATE DATABASE_DEFAULT IN ('GB', 'UK', 'GBR')
                   THEN 'BAC_IMM' ELSE 'TFR_IMM' END
         WHEN LTRIM(RTRIM(ISNULL(s.PT_CURRENCYCODE, ''))) IN ('EUR', 'USD')
         THEN 'TFR_IMM' ELSE 'BAC_IMM' END                      AS PaymentTerms,
    LEFT(LTRIM(RTRIM(COALESCE(NULLIF(LTRIM(RTRIM(s.PT_HEADER_REF2)) COLLATE DATABASE_DEFAULT, ''),
                              s.PT_ORDER_NUMBER COLLATE DATABASE_DEFAULT,
                              s.PT_HEADER_REF   COLLATE DATABASE_DEFAULT, ''))), 20)
                                                                AS SourceDocument,
    LEFT(LTRIM(RTRIM(ISNULL(s.PT_DESCRIPTION, ''))), 30) COLLATE DATABASE_DEFAULT        AS Comments1,
    ''                                                          AS Comments2,
    ''                                                          AS Comments3,
    1                                                           AS Line,
    'S01A'                                                      AS LineSite,
    '18L'                                                       AS PlanCode,
    '999200'                                                    AS GeneralAccounts,
    ''                                                          AS Distribution,
    LEFT(LTRIM(RTRIM(ISNULL(s.PT_DESCRIPTION, ''))), 30) COLLATE DATABASE_DEFAULT        AS LineComment,
    CAST(CASE WHEN LTRIM(RTRIM(ISNULL(s.PT_CURRENCYCODE, ''))) IN ('EUR', 'USD')
                   AND ISNULL(s.PT_CURR_UNAL, 0) <> 0
              THEN ABS(s.PT_CURR_UNAL)
              ELSE ABS(s.PT_UNALLOCATED) END AS decimal(18, 2)) AS LineTransactionAmount,
    -- reference only
    CAST(ISNULL(s.PT_ARCHIVE_FLAG, 0) AS int)                   AS REF_ARCHIVED,
    LTRIM(RTRIM(s.PT_TRANTYPE))                                 AS REF_ACCESS_TYPE,
    CONVERT(varchar(8), s.PT_DATE, 112)                         AS REF_TRAN_DATE,
    LTRIM(RTRIM(s.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT        AS REF_ACCESS_SUPPLIER
FROM src s
JOIN migration.XREF_SAGE_BPS xs
       ON xs.ACCESS_CODE = LTRIM(RTRIM(s.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT
LEFT JOIN dbo.PL_ACCOUNTS a
       ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
        = LTRIM(RTRIM(s.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT;
GO

-- ===========================================================================
--  Checks. Run these straight after creating the views - they are the proof that
--  the fixes landed, and each one would have caught a defect in the originals.
-- ===========================================================================
SELECT 'ITM_LOOKUP rows' AS [check], COUNT(*) AS value FROM migration.ITM_LOOKUP
UNION ALL SELECT 'ITM_LOOKUP with no description', SUM(CASE WHEN ITMDES = '' THEN 1 ELSE 0 END) FROM migration.ITM_LOOKUP
UNION ALL SELECT 'SOH lines', COUNT(*) FROM migration.vw_SOH_V2
UNION ALL SELECT 'SOH orders', COUNT(DISTINCT REF_ORDER_NUMBER) FROM migration.vw_SOH_V2
UNION ALL SELECT 'SOH lines priced at zero', SUM(CASE WHEN GROPRI = 0 THEN 1 ELSE 0 END) FROM migration.vw_SOH_V2
UNION ALL SELECT 'POH lines', COUNT(*) FROM migration.vw_POH_V2
UNION ALL SELECT 'POH lines priced at zero', SUM(CASE WHEN GROPRI = 0 THEN 1 ELSE 0 END) FROM migration.vw_POH_V2
UNION ALL SELECT 'SMR lots', COUNT(*) FROM migration.vw_SMR_V2
UNION ALL SELECT 'SMR lots with no bin', SUM(REF_NO_BIN) FROM migration.vw_SMR_V2
UNION ALL SELECT 'BICX items', COUNT(*) FROM migration.vw_BICX_V2
UNION ALL SELECT 'BICX duplicate documents', COUNT(*) - COUNT(DISTINCT Document) FROM migration.vw_BICX_V2
UNION ALL SELECT 'BICX items with a zero amount', SUM(CASE WHEN TransactionAmount = 0 THEN 1 ELSE 0 END) FROM migration.vw_BICX_V2
UNION ALL SELECT 'BICX archived', SUM(REF_ARCHIVED) FROM migration.vw_BICX_V2
UNION ALL SELECT 'BISX items', COUNT(*) FROM migration.vw_BISX_V2
UNION ALL SELECT 'BISX duplicate documents', COUNT(*) - COUNT(DISTINCT Document) FROM migration.vw_BISX_V2
UNION ALL SELECT 'BISX items with a zero amount', SUM(CASE WHEN TransactionAmount = 0 THEN 1 ELSE 0 END) FROM migration.vw_BISX_V2
UNION ALL SELECT 'BISX archived', SUM(REF_ARCHIVED) FROM migration.vw_BISX_V2;

-- What the account cross-reference could not place. These rows are NOT in the views.
SELECT 'SOH lines dropped - customer has no Sage account' AS [check], COUNT(*) AS value
FROM dbo.ASC_COR_TBL c
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(c.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT
WHERE c.COR_QTY_ORDERED - ISNULL(c.COR_QTY_DELIVERED, 0) > 0
  AND ISNULL(c.COR_ORDER_STATUS, '') IN ('', 'B', 'H')
  AND LTRIM(RTRIM(ISNULL(c.COR_CUSTOMER_CODE, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'POH lines dropped - supplier has no Sage account', COUNT(*)
FROM dbo.ASC_POR_TBL p
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(p.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT
WHERE p.POR_QTY_ORDERED - ISNULL(p.POR_QTY_DELIVERED, 0) - ISNULL(p.POR_QTY_REJECTED, 0) > 0
  AND LTRIM(RTRIM(ISNULL(p.POR_SUP_CODE, ''))) <> '' AND xs.SAGE_CODE IS NULL
UNION ALL
SELECT 'BICX items dropped - customer has no Sage account', COUNT(*)
FROM dbo.SL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPC xc ON xc.ACCESS_CODE = LTRIM(RTRIM(t.ST_COPYCUST)) COLLATE DATABASE_DEFAULT
WHERE t.ST_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.ST_COPYCUST, ''))) <> '' AND xc.SAGE_CODE IS NULL
UNION ALL
SELECT 'BISX items dropped - supplier has no Sage account', COUNT(*)
FROM dbo.PL_TRANSACTIONS t
LEFT JOIN migration.XREF_SAGE_BPS xs ON xs.ACCESS_CODE = LTRIM(RTRIM(t.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT
WHERE t.PT_UNALLOCATED <> 0 AND LTRIM(RTRIM(ISNULL(t.PT_COPYSUPP, ''))) <> '' AND xs.SAGE_CODE IS NULL;

-- The money has to tie. These are the control totals to give finance.
SELECT 'customer open items' AS ledger, COUNT(*) AS items,
       CAST(SUM(GBPAmount) AS decimal(18, 2)) AS gbp_total
FROM migration.vw_BICX_V2
UNION ALL
SELECT 'supplier open items', COUNT(*), CAST(SUM(GBPAmount) AS decimal(18, 2))
FROM migration.vw_BISX_V2;

SELECT 'opening stock' AS what, COUNT(*) AS lots,
       COUNT(DISTINCT ITMREF) AS products,
       CAST(SUM(REF_LOT_VALUE) AS decimal(18, 2)) AS stock_value
FROM migration.vw_SMR_V2;

-- Stock by warehouse, so Marc can see what each decision is worth
SELECT REF_WAREHOUSE AS warehouse, COUNT(*) AS lots,
       COUNT(DISTINCT ITMREF) AS products,
       CAST(SUM(REF_LOT_VALUE) AS decimal(18, 2)) AS stock_value
FROM migration.vw_SMR_V2
GROUP BY REF_WAREHOUSE
ORDER BY stock_value DESC;

-- How many codes in each file are not in the item load.
-- LOAD_ITM holds the RAW Access code; the views emit the CLEANSED one, so both sides
-- have to be cleansed or the check lies - it reported 54% when the true figure is 9%.
WITH itm AS (
    SELECT DISTINCT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(ITMREF)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT AS code
    FROM migration.LOAD_ITM
)
SELECT 'SOH' AS [file], COUNT(*) AS lines,
       SUM(CASE WHEN i.code IS NULL THEN 1 ELSE 0 END) AS product_not_in_item_load,
       SUM(CASE WHEN v.ITMDES = '' THEN 1 ELSE 0 END) AS no_description
FROM migration.vw_SOH_V2 v
LEFT JOIN itm i ON i.code = v.ITMREF COLLATE DATABASE_DEFAULT
UNION ALL
SELECT 'POH', COUNT(*), SUM(CASE WHEN i.code IS NULL THEN 1 ELSE 0 END),
       SUM(CASE WHEN v.ITMDES = '' THEN 1 ELSE 0 END)
FROM migration.vw_POH_V2 v
LEFT JOIN itm i ON i.code = v.ITMREF COLLATE DATABASE_DEFAULT
UNION ALL
SELECT 'SMR', COUNT(*), SUM(CASE WHEN i.code IS NULL THEN 1 ELSE 0 END), 0
FROM migration.vw_SMR_V2 v
LEFT JOIN itm i ON i.code = v.ITMREF COLLATE DATABASE_DEFAULT;

-- Stock sitting on products we are not migrating, by warehouse. 2,176 of 8,479 lots.
WITH itm AS (
    SELECT DISTINCT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
               REPLACE(LTRIM(RTRIM(ITMREF)), CHAR(160), ''), ' ', ''), '&', ''), '(', ''), ')', ''), '.', '-'))
               COLLATE DATABASE_DEFAULT AS code
    FROM migration.LOAD_ITM
)
SELECT v.REF_WAREHOUSE AS warehouse,
       COUNT(*) AS lots,
       SUM(CASE WHEN i.code IS NULL THEN 1 ELSE 0 END) AS lots_on_unmigrated_products,
       CAST(SUM(CASE WHEN i.code IS NULL THEN v.REF_LOT_VALUE ELSE 0 END) AS decimal(18,2)) AS value_at_risk
FROM migration.vw_SMR_V2 v
LEFT JOIN itm i ON i.code = v.ITMREF COLLATE DATABASE_DEFAULT
GROUP BY v.REF_WAREHOUSE
ORDER BY value_at_risk DESC;

