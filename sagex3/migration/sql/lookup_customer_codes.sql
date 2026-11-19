-- lookup_customer_codes.sql  -  READ ONLY, changes nothing.  Run against SDILive.
--
-- Access customer code -> new Sage X3 code, for the codes listed below (edit the list).
-- One row per code asked: the Sage code from migration.XREF_SAGE_BPC (blank = no Sage code yet),
-- how it was matched, the Access name, and whether the account traded in the last 24 months.
-- First used 19 Nov for Sue Rogers' list.

SET NOCOUNT ON;

SELECT k.code                                                AS access_code,
       ISNULL(LTRIM(RTRIM(x.SAGE_CODE)), '')                 AS sage_code,
       ISNULL(LTRIM(RTRIM(x.MATCHED_BY)), '')                AS matched_by,
       ISNULL(LTRIM(RTRIM(a.CUNAME)), '(not in SL_ACCOUNTS)') AS access_name,
       CONVERT(varchar(10), (SELECT MAX(t.ST_DATE) FROM dbo.SL_TRANSACTIONS t
                             WHERE LTRIM(RTRIM(t.ST_COPYCUST)) COLLATE DATABASE_DEFAULT = k.code), 23) AS last_ledger_entry
FROM (VALUES ('CRC01'), ('ISL03'), ('CRL02'), ('HCL01'), ('HCC01'), ('SSP02'), ('GOO07')) k (code)
LEFT JOIN migration.XREF_SAGE_BPC x
       ON LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT = k.code COLLATE DATABASE_DEFAULT
LEFT JOIN dbo.SL_ACCOUNTS a
       ON LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = k.code COLLATE DATABASE_DEFAULT
ORDER BY k.code;
