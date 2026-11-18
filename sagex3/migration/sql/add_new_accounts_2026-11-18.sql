-- add_new_accounts_2026-11-18.sql  -  changes ONLY our own migration tables (migration.XREF_SAGE_BPC / XREF_SAGE_BPS)
--
-- The trading Access accounts that have no Sage code (extract_accounts.sql NEWC / NEWS, 18 Nov), with the
-- new codes from build_customers_to_add.py / build_new_suppliers.py. Without a code the views drop their
-- open items and orders - why AFB01, MUN01, TDG03, BWS01 and KOM01's late-October invoices were missing.
--   customers: 32 (left out: ESD01, FSC01 ledger accounts; VIV01, SDI02 intercompany; IBS01 no address)
--   suppliers: 35 (left out: 56 employee expense accounts with nothing open, 5 non-suppliers)
--
-- SAFE TO RE-RUN: it only ADDS an account that isn't there; it never deletes (the generated script did
-- DELETE ... WHERE MATCHED_BY = 'new account', which would have removed the 27 Oct accounts). Explicit
-- transaction and COMMIT (4 Nov: an implicit transaction rolled back when the tab closed), then checks.
-- Codes only - names are read from Access as it runs. Run BEFORE the transaction extract (Thursday).
USE SDILive;
GO
SET NOCOUNT ON;
SET IMPLICIT_TRANSACTIONS OFF;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

INSERT INTO migration.XREF_SAGE_BPC (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)
SELECT p.ACCESS_CODE, p.SAGE_CODE, LTRIM(RTRIM(a.CUNAME)), LTRIM(RTRIM(a.CUNAME)), 'new account'
FROM (VALUES
    ('AFB01', 'ALF100'),
    ('BML01', 'BAR100'),
    ('BOT04', 'BOO105'),
    ('BEL01', 'BRA101'),
    ('BWS01', 'BRI101'),
    ('CSL03', 'CHE100'),
    ('OSE01', 'CHI100'),
    ('CRC01', 'CRC100'),
    ('CTS01', 'CTS100'),
    ('FWP01', 'FOU100'),
    ('GFL02', 'GEM100'),
    ('GUL02', 'GII100'),
    ('ISL04', 'INN102'),
    ('ISG01', 'ISG100'),
    ('JMS01', 'JMS100'),
    ('KOM01', 'KOM100'),
    ('KGL03', 'KUR103'),
    ('LBU02', 'LMB100'),
    ('MAR38', 'MAR102'),
    ('MRO01', 'MEN101'),
    ('MUN01', 'MUN100'),
    ('OTL01', 'OFF100'),
    ('PLL01', 'PLA101'),
    ('CPG01', 'PUM100'),
    ('PSL01', 'PUR100'),
    ('TIE16E', 'TEC124'),
    ('TIE10FR', 'TEC125'),
    ('TDG03', 'TOP103'),
    ('UAB02', 'UAB100'),
    ('WHS02', 'WAN102'),
    ('WPI01', 'WAT101'),
    ('WJS01', 'WIL103')
) p (ACCESS_CODE, SAGE_CODE)
JOIN dbo.SL_ACCOUNTS a ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPC x
                  WHERE LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
                     OR LTRIM(RTRIM(x.SAGE_CODE)) COLLATE DATABASE_DEFAULT = p.SAGE_CODE COLLATE DATABASE_DEFAULT);
DECLARE @c int = @@ROWCOUNT;

INSERT INTO migration.XREF_SAGE_BPS (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)
SELECT p.ACCESS_CODE, p.SAGE_CODE, LTRIM(RTRIM(a.SUNAME)), LTRIM(RTRIM(a.SUNAME)), 'new account'
FROM (VALUES
    ('AGE01', 'ART501'),
    ('GRD01', 'BRE500'),
    ('CSE02', 'CAL501'),
    ('CFR01', 'CHL501'),
    ('MCG02', 'CHL502'),
    ('CLL01', 'CLA502'),
    ('CUE01', 'CON505'),
    ('CIL01', 'CRA501'),
    ('COR04', 'DAN501'),
    ('DCD01', 'DAV501'),
    ('DGS01', 'DGS500'),
    ('EDC01', 'EDW501'),
    ('EMA01', 'EMA500'),
    ('FBS01', 'FEN500'),
    ('FEW01', 'FLI500'),
    ('IJE01', 'IAN501'),
    ('KNI02', 'IAN502'),
    ('KWE01', 'KAS500'),
    ('SNO01', 'KER500'),
    ('KRD01', 'KRD500'),
    ('MER05', 'LEE501'),
    ('BAT02', 'NIC500'),
    ('GAR03', 'NIC501'),
    ('PBE01', 'PAU501'),
    ('PIF01', 'PIN500'),
    ('SAG02', 'SAG500'),
    ('SCI01', 'SCA501'),
    ('SDS05', 'SEE500'),
    ('SAE01', 'STA502'),
    ('SJD01', 'STE503'),
    ('TWW02', 'TUF500'),
    ('UAL01', 'UNI501'),
    ('WGS02', 'WGS500'),
    ('WLE014', 'WIL502'),
    ('YME01', 'YUR500')
) p (ACCESS_CODE, SAGE_CODE)
JOIN dbo.PL_ACCOUNTS a ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPS x
                  WHERE LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
                     OR LTRIM(RTRIM(x.SAGE_CODE)) COLLATE DATABASE_DEFAULT = p.SAGE_CODE COLLATE DATABASE_DEFAULT);
DECLARE @s int = @@ROWCOUNT;

COMMIT TRANSACTION;
SELECT 'ADDED' AS [check], @c AS customers_added, @s AS suppliers_added,
       '32 / 35 on the first run, 0 / 0 on a re-run' AS expected;
GO
-- after the commit, from the tables themselves
SELECT 'AFTER COMMIT' AS [check],
       (SELECT COUNT(*) FROM migration.XREF_SAGE_BPC) AS customers_in_xref,
       (SELECT COUNT(*) FROM migration.XREF_SAGE_BPS) AS suppliers_in_xref,
       '303 + 32 = 335 and 707 + 35 = 742' AS expected;
GO
