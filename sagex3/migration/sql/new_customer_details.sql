-- new_customer_details.sql  -  READ ONLY, changes nothing
--
-- Access details for the 87 live customers being added to Sage X3 (Customers_to_add.xlsx).
-- Grid 1: the customer rows, as the customer import is built from (vw_BPC).
-- Grid 2: their delivery addresses (SL_ADDRESSES).
-- Run the whole file. Results To File, tab delimited, and send it back.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#codes') IS NOT NULL DROP TABLE #codes;
CREATE TABLE #codes (code varchar(20) COLLATE DATABASE_DEFAULT PRIMARY KEY);
INSERT INTO #codes (code) VALUES
    ('ASA03'), ('BCL01'), ('BBL02'), ('BOT01'), ('BOT02'), ('BOT05'), ('BUN03'), ('BUN05'), ('CSL01'), ('CFL01'),
    ('CLL01'), ('CBT05'), ('CTB03'), ('CTB06'), ('CCL06'), ('CGL04'), ('CNG01'), ('CRL02'), ('TDG02'), ('DWC01'),
    ('DFU01'), ('EGI01'), ('ELF01'), ('HAR21'), ('ISL03'), ('IBS01'), ('KDM01'), ('KCL02'), ('KGL02'), ('KGL06'),
    ('KGL07'), ('LSL04'), ('LSL05'), ('MAR002'), ('MMM01'), ('NAA01'), ('NMG01'), ('NEX04'), ('NIC08'), ('NBL02'),
    ('PER13'), ('PER14'), ('RTL01'), ('SSL05'), ('KGL08'), ('KGL04'), ('SIM13'), ('SOF01'), ('SSP01'), ('SSP02'),
    ('TIE02E'), ('TIE02POL'), ('RYO03'), ('TIE06E'), ('TIE02UK'), ('TIE02PLPL'), ('TIE08E'), ('TIE10E'), ('TIE11E'), ('TIE11EPL'),
    ('TIE02EFR'), ('TIE02ENL'), ('TIE10EFR'), ('TIE02EPL'), ('TIE08ENO'), ('TIE06EAT'), ('TIE17E'), ('TIE02PLF'), ('TIE02PLN'), ('TIE13E'),
    ('RYO04'), ('TES03'), ('TEL03'), ('UUL01'), ('UUL04'), ('UUL06'), ('UUL03'), ('WUL02'), ('WUL01'), ('WBI02'),
    ('WBI01'), ('WBS02'), ('WBS01'), ('WMM01'), ('WMM02'), ('WWF01'), ('YOR07');

SELECT b.*
FROM migration.vw_BPC b
JOIN #codes k ON k.code = LTRIM(RTRIM(b.BPCNUM)) COLLATE DATABASE_DEFAULT
ORDER BY b.BPCNUM;

SELECT a.*
FROM dbo.SL_ADDRESSES a
JOIN #codes k ON k.code = LTRIM(RTRIM(a.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT
ORDER BY a.AD_ACC_CODE, a.AD_CODE;

-- Check: should say 87 and 87
SELECT (SELECT COUNT(*) FROM #codes) AS codes_asked,
       (SELECT COUNT(DISTINCT LTRIM(RTRIM(b.BPCNUM))) FROM migration.vw_BPC b
         JOIN #codes k ON k.code = LTRIM(RTRIM(b.BPCNUM)) COLLATE DATABASE_DEFAULT) AS customers_found;
GO
