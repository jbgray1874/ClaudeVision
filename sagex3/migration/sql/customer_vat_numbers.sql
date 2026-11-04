-- customer_vat_numbers.sql  -  READ ONLY, changes nothing (no temporary tables either)
--
-- Every VAT number Access holds for each customer in the migration, so the gaps in the customer
-- file (YA004BPC, column EECNUM) can be filled. The account record (SL_ACCOUNTS.CU_VAT_REG_NO)
-- has 90; the addresses (SL_ADDRESSES.AD_VAT_REG_NO) have 631 rows, and the old address copy
-- (SL_ADDRESSES_COPYA) 122. One row per customer, address and number.
--
-- Run it after add_new_accounts_to_xref.sql, so the 86 new customers are in the cross-reference.
-- Results To File, tab delimited, one file, and send it back. Each grid starts with a label.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'CHECK' AS grid, 'as at' AS item, CONVERT(varchar(19), GETDATE(), 120) AS value
UNION ALL SELECT 'CHECK', 'customers in the cross-reference', CAST(COUNT(*) AS varchar(10)) FROM migration.XREF_SAGE_BPC;

SELECT 'VAT' AS grid,
       LTRIM(RTRIM(x.SAGE_CODE))                                        AS sage,
       LTRIM(RTRIM(x.ACCESS_CODE))                                      AS access,
       v.source,
       v.address_code,
       v.invoice_address,
       v.statement_address,
       v.primary_address,
       v.country,
       REPLACE(REPLACE(LTRIM(RTRIM(v.vat)), CHAR(9), ' '), CHAR(13), '') AS vat
FROM migration.XREF_SAGE_BPC x
CROSS APPLY (
    SELECT 'ACCOUNT' AS source, '' AS address_code, '' AS invoice_address, '' AS statement_address,
           '' AS primary_address, '' AS country, a.CU_VAT_REG_NO AS vat
    FROM dbo.SL_ACCOUNTS a
    WHERE LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(a.CU_VAT_REG_NO, ''))) <> ''
    UNION ALL
    SELECT 'ADDRESS', LTRIM(RTRIM(d.AD_CODE)), CAST(d.AD_INV_ADDRESS AS varchar(5)), CAST(d.AD_STAT_ADDRESS AS varchar(5)),
           CAST(d.SL_AD_PRIMARY AS varchar(5)), LTRIM(RTRIM(ISNULL(d.AD_COUNTRY_CODE, ''))), d.AD_VAT_REG_NO
    FROM dbo.SL_ADDRESSES d
    WHERE LTRIM(RTRIM(d.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(d.AD_VAT_REG_NO, ''))) <> ''
    UNION ALL
    -- the old copy: only the columns it is known to share with SL_ADDRESSES
    SELECT 'ADDRESS_COPYA', LTRIM(RTRIM(c.AD_CODE)), '', '', '', '', c.AD_VAT_REG_NO
    FROM dbo.SL_ADDRESSES_COPYA c
    WHERE LTRIM(RTRIM(c.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(x.ACCESS_CODE)) COLLATE DATABASE_DEFAULT
      AND LTRIM(RTRIM(ISNULL(c.AD_VAT_REG_NO, ''))) <> ''
) v
ORDER BY sage, v.source, v.address_code;
GO
