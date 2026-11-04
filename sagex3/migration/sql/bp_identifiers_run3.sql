-- bp_identifiers_run3.sql  -  READ ONLY, changes nothing (one temporary table, in tempdb)
--
-- Everything Access holds for the 11 suppliers and 6 customers X3 rejected in Run 2, every
-- column, so nothing that could fill a gap is missed: a VAT or registration number in a column
-- we never mapped, a county / state on the customer addresses (X3's XSAT error).
-- Small: 11 supplier rows, 6 customer rows, and those customers' addresses (about 1,400).
--
-- Results To File, tab delimited, one file, and send it back. Each grid starts with a label.
USE SDILive;
GO
SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

IF OBJECT_ID('tempdb..#want') IS NOT NULL DROP TABLE #want;
CREATE TABLE #want (kind char(1), sage varchar(10) COLLATE DATABASE_DEFAULT,
                    access varchar(20) COLLATE DATABASE_DEFAULT NULL);
INSERT INTO #want (kind, sage) VALUES
    ('S', 'AMG500'), ('S', 'AGE500'), ('S', 'GAL500'), ('S', 'GRO500'), ('S', 'ICE500'), ('S', 'PLS500'),
    ('S', 'VUS500'), ('S', 'SOG500'), ('S', 'BAL500'), ('S', 'BUR500'), ('S', 'ECO500'),
    ('C', 'TEC100'), ('C', 'TEC105'), ('C', 'UNI103'), ('C', 'DRE100'), ('C', 'MAR101'), ('C', 'PER101');

-- the Access code, from the cross-reference
UPDATE w SET access = LTRIM(RTRIM(x.ACCESS_CODE))
FROM #want w JOIN migration.XREF_SAGE_BPS x ON x.SAGE_CODE COLLATE DATABASE_DEFAULT = w.sage
WHERE w.kind = 'S';
UPDATE w SET access = LTRIM(RTRIM(x.ACCESS_CODE))
FROM #want w JOIN migration.XREF_SAGE_BPC x ON x.SAGE_CODE COLLATE DATABASE_DEFAULT = w.sage
WHERE w.kind = 'C' AND w.access IS NULL;
-- the accounts added on 27 Oct, in case add_new_accounts_to_xref.sql hasn't run
UPDATE w SET access = v.access
FROM #want w
JOIN (VALUES ('BAL500', 'BAL01'), ('BUR500', 'BVC01'), ('ECO500', 'ECO04'), ('DRE100', 'DWC01'),
             ('MAR101', 'MAR002'), ('PER101', 'PER13'), ('TEC105', 'RYO03'), ('UNI103', 'UUL04')) v (sage, access)
  ON v.sage = w.sage
WHERE w.access IS NULL;

SELECT 'CODES' AS grid, kind, sage, ISNULL(access, '(not found)') AS access FROM #want;

-- the column names, so the rows below can be read
SELECT 'COLUMN' AS grid, t.name AS [table], c.column_id, c.name AS [column]
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id AND s.name = 'dbo'
JOIN sys.columns c ON c.object_id = t.object_id
WHERE t.name IN ('PL_ACCOUNTS', 'SL_ACCOUNTS', 'SL_ADDRESSES')
ORDER BY t.name, c.column_id;

SELECT 'PLACC' AS grid, p.*
FROM dbo.PL_ACCOUNTS p
JOIN #want w ON w.kind = 'S' AND LTRIM(RTRIM(p.SUCODE)) COLLATE DATABASE_DEFAULT = w.access;

SELECT 'SLACC' AS grid, a.*
FROM dbo.SL_ACCOUNTS a
JOIN #want w ON w.kind = 'C' AND LTRIM(RTRIM(a.CUCODE)) COLLATE DATABASE_DEFAULT = w.access;

SELECT 'SLADR' AS grid, d.*
FROM dbo.SL_ADDRESSES d
JOIN #want w ON w.kind = 'C' AND LTRIM(RTRIM(d.AD_ACC_CODE)) COLLATE DATABASE_DEFAULT = w.access;
GO
