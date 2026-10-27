-- add_new_accounts_to_xref.sql  -  run once, before the re-export
--
-- Brings migration.XREF_SAGE_BPC / XREF_SAGE_BPS up to date without re-running the full
-- xref_sage_codes.sql:
--   1. the two version-3 corrections (WCP02 is WCP101; HCL02 is HOT100)
--   2. the 86 new customer accounts   (same as xref_new_customer_accounts.sql)
--   3. the 83 new supplier accounts   (same as xref_new_supplier_accounts.sql)
-- Re-runnable. Then re-export views_v2.sql and product_suppliers_v3.sql grid 2.
USE SDILive;
GO
SET NOCOUNT ON;
UPDATE migration.XREF_SAGE_BPC SET SAGE_CODE = 'WCP101', MATCHED_BY = 'manual' WHERE ACCESS_CODE = 'WCP02';
INSERT INTO migration.XREF_SAGE_BPC (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)
SELECT LTRIM(RTRIM(a.CUCODE)), 'HOT100', LTRIM(RTRIM(a.CUNAME)), LTRIM(RTRIM(a.CUNAME)), 'manual'
FROM dbo.SL_ACCOUNTS a
WHERE LTRIM(RTRIM(a.CUCODE)) = 'HCL02'
  AND NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPC x WHERE x.ACCESS_CODE = 'HCL02');
GO

DELETE FROM migration.XREF_SAGE_BPC WHERE MATCHED_BY = 'new account';
INSERT INTO migration.XREF_SAGE_BPC (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)
SELECT p.ACCESS_CODE, p.SAGE_CODE, LTRIM(RTRIM(a.CUNAME)), LTRIM(RTRIM(a.CUNAME)), 'new account'
FROM (VALUES
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
    ('YOR07', 'YOR100')
) p (ACCESS_CODE, SAGE_CODE)
JOIN dbo.SL_ACCOUNTS a ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPC x
                   WHERE x.ACCESS_CODE = p.ACCESS_CODE COLLATE DATABASE_DEFAULT);

-- Check: added = expected, and a new code must never already belong to another account
SELECT COUNT(*) AS new_accounts_added, 86 AS expected,
       (SELECT COUNT(*) FROM migration.XREF_SAGE_BPC n JOIN migration.XREF_SAGE_BPC o
          ON o.SAGE_CODE = n.SAGE_CODE AND o.ACCESS_CODE <> n.ACCESS_CODE
        WHERE n.MATCHED_BY = 'new account') AS new_codes_clashing
FROM migration.XREF_SAGE_BPC WHERE MATCHED_BY = 'new account';
GO

DELETE FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account';
INSERT INTO migration.XREF_SAGE_BPS (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)
SELECT p.ACCESS_CODE, p.SAGE_CODE, LTRIM(RTRIM(a.SUNAME)), LTRIM(RTRIM(a.SUNAME)), 'new account'
FROM (VALUES
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
    ('ZPK01', 'ZPK500')
) p (ACCESS_CODE, SAGE_CODE)
JOIN dbo.PL_ACCOUNTS a ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT
WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPS x
                   WHERE x.ACCESS_CODE = p.ACCESS_CODE COLLATE DATABASE_DEFAULT);

-- Check: added = expected, and a new code must never already belong to another account
SELECT COUNT(*) AS new_accounts_added, 83 AS expected,
       (SELECT COUNT(*) FROM migration.XREF_SAGE_BPS n JOIN migration.XREF_SAGE_BPS o
          ON o.SAGE_CODE = n.SAGE_CODE AND o.ACCESS_CODE <> n.ACCESS_CODE
        WHERE n.MATCHED_BY = 'new account') AS new_codes_clashing
FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account';
GO
