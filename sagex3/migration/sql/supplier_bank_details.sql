-- supplier_bank_details.sql  -  READ ONLY, changes nothing (temporary table only, in tempdb)
--
-- Bank details for YA004BPSC (supplier banks): sort code and account number from PL_ACCOUNTS,
-- for every supplier with a Sage code - the 623 in the cross-reference plus the 83 new ones
-- (written in below, so no table changes). One grid, small (one row per supplier).
--
-- CONFIDENTIAL: bank account details. Results To File, tab delimited, send back, then delete the
-- local copy. Not for email outside SDI.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#newsup') IS NOT NULL DROP TABLE #newsup;
CREATE TABLE #newsup (ACCESS_CODE varchar(20) COLLATE DATABASE_DEFAULT PRIMARY KEY, SAGE_CODE varchar(10) COLLATE DATABASE_DEFAULT NOT NULL);
INSERT INTO #newsup (ACCESS_CODE, SAGE_CODE) VALUES
    ('AVL01', 'ACT500'), ('ADP01', 'ADR500'), ('PAR07', 'ASH502'), ('AAL03', 'ASS500'), ('AGL01', 'ATE500'), ('AGL01PL', 'ATE501'),
    ('BAL01', 'BAL500'), ('BWL01', 'BIA500'), ('BCW01', 'BIC500'), ('BVC01', 'BUR500'), ('COT02', 'CAP500'), ('CHS01', 'CAS500'),
    ('CLM01', 'CLA501'), ('CLC01', 'CLC500'), ('CFL02', 'CON504'), ('CCC02', 'CRO501'), ('CSW01', 'CSW500'), ('DA001', 'DEB500'),
    ('DIE01', 'DIE500'), ('EMS01', 'EAS501'), ('ECO04', 'ECO500'), ('EMT01', 'ELE500'), ('ELM01', 'ELL500'), ('EMB01', 'EMI500'),
    ('EPL03', 'ENG500'), ('ERL03', 'EUR501'), ('FFL04', 'FOR501'), ('FFL01', 'FOR502'), ('FML01', 'FOR503'), ('FRE04', 'FRE501'),
    ('GJW01', 'GJW500'), ('GIL01', 'GLO500'), ('GRG01', 'GRG500'), ('HRC01', 'HOY500'), ('HUN04', 'HUN500'), ('IMZ01', 'IMA500'),
    ('JWR01', 'JAC500'), ('JCE01', 'JCE500'), ('JLC01', 'JLC500'), ('JLY01', 'JLY500'), ('JRP01', 'JRP500'), ('LTL03', 'LIU500'),
    ('LKW03', 'LKW500'), ('LKW02', 'LKW501'), ('MCH01', 'MAS501'), ('MXM01', 'MAT501'), ('MLS02', 'MID500'), ('MNL01', 'MIK501'),
    ('MCO02', 'MIL501'), ('MPR01', 'MOT501'), ('MGT01', 'MYG500'), ('NTL02', 'NIN500'), ('NTL02PL', 'NIN501'), ('OCT01', 'OCT501'),
    ('OSI01', 'ONE500'), ('TPC01', 'PAC501'), ('PGB02', 'PAR501'), ('PRL04', 'PER501'), ('PCD03PL', 'PIO500'), ('PDC02', 'PIO501'),
    ('QRD01', 'QRD500'), ('TRG01', 'REC501'), ('RCL02', 'RIV501'), ('SMI03', 'ROB500'), ('AWL03', 'ROB501'), ('SRD01', 'SLI501'),
    ('SLM01', 'SLM500'), ('SDC01', 'STA501'), ('SJS01', 'STE502'), ('TIL01', 'STU501'), ('TEC04', 'TEC501'), ('TFS02', 'TRU501'),
    ('TTS01', 'TTS500'), ('UKF01', 'UKF500'), ('TUW01', 'UPH501'), ('WRC03', 'WEA500'), ('WIL21', 'WHI501'), ('WAP02', 'WIL501'),
    ('XYS01', 'XIA501'), ('XMD01', 'XIA502'), ('XYS01PL', 'XIA503'), ('JZH01', 'ZHE500'), ('ZPK01', 'ZPK500');

SELECT COALESCE(x.SAGE_CODE, n.SAGE_CODE)                         AS sage_code,
       LTRIM(RTRIM(a.SUCODE))                                     AS access_code,
       LTRIM(RTRIM(ISNULL(a.SU_BANK_SORT, '')))                   AS sort_code,
       LTRIM(RTRIM(ISNULL(a.SU_BANK_AC_NO, '')))                  AS account_number,
       LTRIM(RTRIM(ISNULL(a.SU_BANK_AC_NAME, '')))                AS account_name,
       LTRIM(RTRIM(ISNULL(a.SU_BANK_BANKNAME, '')))               AS bank_name,
       LTRIM(RTRIM(ISNULL(a.SU_BANK_BACSREF, '')))                AS bacs_reference,
       LTRIM(RTRIM(ISNULL(a.SU_COUNTRY_CODE, '')))                AS country,
       LTRIM(RTRIM(ISNULL(a.SUCURRENCYCODE, '')))                 AS currency
FROM dbo.PL_ACCOUNTS a
LEFT JOIN migration.XREF_SAGE_BPS x ON x.ACCESS_CODE = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
LEFT JOIN #newsup n ON n.ACCESS_CODE = LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT
WHERE COALESCE(x.SAGE_CODE, n.SAGE_CODE) IS NOT NULL
ORDER BY 1;
GO
