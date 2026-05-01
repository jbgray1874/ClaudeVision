-- Run once against the database that holds historical_quote_* tables.
-- Adds a human-oriented JSON column for drawing / estimate reconciliation (pretty-printed by the loader).

IF COL_LENGTH('dbo.historical_quote_header', 'readable_extract_json') IS NULL
BEGIN
    ALTER TABLE dbo.historical_quote_header ADD readable_extract_json NVARCHAR(MAX) NULL;
END
GO
