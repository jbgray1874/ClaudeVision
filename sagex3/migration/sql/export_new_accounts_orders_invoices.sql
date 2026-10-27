-- export_new_accounts_orders_invoices.sql  -  READ ONLY, changes nothing (temporary tables only, in tempdb)
--
-- The open orders and invoices of the 86 new customers and 83 new suppliers ONLY - the rows
-- the views drop because those accounts are not in the cross-reference. Each grid is the view's
-- own query (views_v2.sql) with the new codes written in, so the columns are exactly the views'.
-- No other SQL is needed first.
--
-- Four grids. Results To File, tab delimited, one file, and send it back.
--   1  open sales orders     (YA004SOHPJ)    3  customer open items  (YA004BICX)
--   2  open purchase orders  (YA004POH)      4  supplier open items  (YA004BISX)
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#newcus') IS NOT NULL DROP TABLE #newcus;
CREATE TABLE #newcus (ACCESS_CODE varchar(20) COLLATE DATABASE_DEFAULT PRIMARY KEY, SAGE_CODE varchar(10) COLLATE DATABASE_DEFAULT NOT NULL);
INSERT INTO #newcus (ACCESS_CODE, SAGE_CODE) VALUES
    ('ASA03', 'ACN100'),
    ('BCL01', 'BEA100'),
    ('BBL02', 'BEA101'),
    ('BOT01', 'BOO102'),
    ('BOT02', 'BOO103'),
    ('BOT05', 'BOO104'),
    ('BUN03', 'BUN100'),
    ('BUN05', 'BUN101'),
    ('CSL01', 'CAN100'),
    ('CFL01', 'CAR101'),
    ('CLL01', 'CAS100'),
    ('CBT05', 'CHA101'),
    ('CTB03', 'CHA102'),
    ('CTB06', 'CHA103'),
    ('CCL06', 'COR101'),
    ('CGL04', 'COR102'),
    ('CNG01', 'COS100'),
    ('CRL02', 'CUC100'),
    ('TDG02', 'DEL101'),
    ('DWC01', 'DRE100'),
    ('DFU01', 'DRW100'),
    ('EGI01', 'EGO100'),
    ('ELF01', 'ELF100'),
    ('HAR21', 'HAR101'),
    ('ISL03', 'INN101'),
    ('KDM01', 'KDM100'),
    ('KCL02', 'KIM101'),
    ('KGL02', 'KUR100'),
    ('KGL06', 'KUR101'),
    ('KGL07', 'KUR102'),
    ('LSL04', 'LIN101'),
    ('LSL05', 'LIN102'),
    ('MAR002', 'MAR101'),
    ('MMM01', 'MEL100'),
    ('NAA01', 'NAM100'),
    ('NMG01', 'NEW101'),
    ('NEX04', 'NEX100'),
    ('NIC08', 'NIC100'),
    ('NBL02', 'NUT101'),
    ('PER13', 'PER101'),
    ('PER14', 'PER102'),
    ('RTL01', 'ROL101'),
    ('SSL05', 'SAN100'),
    ('KGL08', 'SAS100'),
    ('KGL04', 'SAS101'),
    ('SIM13', 'SIM101'),
    ('SOF01', 'SOF100'),
    ('SSP01', 'SSP100'),
    ('SSP02', 'SSP101'),
    ('TIE02E', 'TEC103'),
    ('TIE02POL', 'TEC104'),
    ('RYO03', 'TEC105'),
    ('TIE06E', 'TEC106'),
    ('TIE02UK', 'TEC107'),
    ('TIE02PLPL', 'TEC108'),
    ('TIE08E', 'TEC109'),
    ('TIE10E', 'TEC110'),
    ('TIE11E', 'TEC111'),
    ('TIE11EPL', 'TEC112'),
    ('TIE02EFR', 'TEC113'),
    ('TIE02ENL', 'TEC114'),
    ('TIE10EFR', 'TEC115'),
    ('TIE02EPL', 'TEC116'),
    ('TIE08ENO', 'TEC117'),
    ('TIE06EAT', 'TEC118'),
    ('TIE17E', 'TEC119'),
    ('TIE02PLF', 'TEC120'),
    ('TIE02PLN', 'TEC121'),
    ('TIE13E', 'TEC122'),
    ('RYO04', 'TEC123'),
    ('TES03', 'TES102'),
    ('TEL03', 'TOP102'),
    ('UUL01', 'UNI102'),
    ('UUL04', 'UNI103'),
    ('UUL06', 'UNI104'),
    ('UUL03', 'UNI105'),
    ('WUL02', 'WEL100'),
    ('WUL01', 'WEL101'),
    ('WBI02', 'WHI101'),
    ('WBI01', 'WHI102'),
    ('WBS02', 'WIL101'),
    ('WBS01', 'WIL102'),
    ('WMM01', 'WMM100'),
    ('WMM02', 'WMM101'),
    ('WWF01', 'WOR100'),
    ('YOR07', 'YOR100');

IF OBJECT_ID('tempdb..#newsup') IS NOT NULL DROP TABLE #newsup;
CREATE TABLE #newsup (ACCESS_CODE varchar(20) COLLATE DATABASE_DEFAULT PRIMARY KEY, SAGE_CODE varchar(10) COLLATE DATABASE_DEFAULT NOT NULL);
INSERT INTO #newsup (ACCESS_CODE, SAGE_CODE) VALUES
    ('AVL01', 'ACT500'),
    ('ADP01', 'ADR500'),
    ('PAR07', 'ASH502'),
    ('AAL03', 'ASS500'),
    ('AGL01', 'ATE500'),
    ('AGL01PL', 'ATE501'),
    ('BAL01', 'BAL500'),
    ('BWL01', 'BIA500'),
    ('BCW01', 'BIC500'),
    ('BVC01', 'BUR500'),
    ('COT02', 'CAP500'),
    ('CHS01', 'CAS500'),
    ('CLM01', 'CLA501'),
    ('CLC01', 'CLC500'),
    ('CFL02', 'CON504'),
    ('CCC02', 'CRO501'),
    ('CSW01', 'CSW500'),
    ('DA001', 'DEB500'),
    ('DIE01', 'DIE500'),
    ('EMS01', 'EAS501'),
    ('ECO04', 'ECO500'),
    ('EMT01', 'ELE500'),
    ('ELM01', 'ELL500'),
    ('EMB01', 'EMI500'),
    ('EPL03', 'ENG500'),
    ('ERL03', 'EUR501'),
    ('FFL04', 'FOR501'),
    ('FFL01', 'FOR502'),
    ('FML01', 'FOR503'),
    ('FRE04', 'FRE501'),
    ('GJW01', 'GJW500'),
    ('GIL01', 'GLO500'),
    ('GRG01', 'GRG500'),
    ('HRC01', 'HOY500'),
    ('HUN04', 'HUN500'),
    ('IMZ01', 'IMA500'),
    ('JWR01', 'JAC500'),
    ('JCE01', 'JCE500'),
    ('JLC01', 'JLC500'),
    ('JLY01', 'JLY500'),
    ('JRP01', 'JRP500'),
    ('LTL03', 'LIU500'),
    ('LKW03', 'LKW500'),
    ('LKW02', 'LKW501'),
    ('MCH01', 'MAS501'),
    ('MXM01', 'MAT501'),
    ('MLS02', 'MID500'),
    ('MNL01', 'MIK501'),
    ('MCO02', 'MIL501'),
    ('MPR01', 'MOT501'),
    ('MGT01', 'MYG500'),
    ('NTL02', 'NIN500'),
    ('NTL02PL', 'NIN501'),
    ('OCT01', 'OCT501'),
    ('OSI01', 'ONE500'),
    ('TPC01', 'PAC501'),
    ('PGB02', 'PAR501'),
    ('PRL04', 'PER501'),
    ('PCD03PL', 'PIO500'),
    ('PDC02', 'PIO501'),
    ('QRD01', 'QRD500'),
    ('TRG01', 'REC501'),
    ('RCL02', 'RIV501'),
    ('SMI03', 'ROB500'),
    ('AWL03', 'ROB501'),
    ('SRD01', 'SLI501'),
    ('SLM01', 'SLM500'),
    ('SDC01', 'STA501'),
    ('SJS01', 'STE502'),
    ('TIL01', 'STU501'),
    ('TEC04', 'TEC501'),
    ('TFS02', 'TRU501'),
    ('TTS01', 'TTS500'),
    ('UKF01', 'UKF500'),
    ('TUW01', 'UPH501'),
    ('WRC03', 'WEA500'),
    ('WIL21', 'WHI501'),
    ('WAP02', 'WIL501'),
    ('XYS01', 'XIA501'),
    ('XMD01', 'XIA502'),
    ('XYS01PL', 'XIA503'),
    ('JZH01', 'ZHE500'),
    ('ZPK01', 'ZPK500');

-- ===== 1. vw_SOH_V2, new accounts only =====
;WITH src AS (
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
JOIN #newcus xc
       ON xc.ACCESS_CODE = LTRIM(RTRIM(s.COR_CUSTOMER_CODE)) COLLATE DATABASE_DEFAULT;

-- ===== 2. vw_POH_V2, new accounts only =====
;WITH src AS (
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
JOIN #newsup xs
       ON xs.ACCESS_CODE = LTRIM(RTRIM(s.POR_SUP_CODE)) COLLATE DATABASE_DEFAULT;

-- ===== 3. vw_BICX_V2, new accounts only =====
;WITH src AS (
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
JOIN #newcus xc
       ON xc.ACCESS_CODE = LTRIM(RTRIM(s.ST_COPYCUST)) COLLATE DATABASE_DEFAULT;

-- ===== 4. vw_BISX_V2, new accounts only =====
;WITH src AS (
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
JOIN #newsup xs
       ON xs.ACCESS_CODE = LTRIM(RTRIM(s.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT
LEFT JOIN dbo.PL_ACCOUNTS a
       ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
        = LTRIM(RTRIM(s.PT_COPYSUPP)) COLLATE DATABASE_DEFAULT;
GO
