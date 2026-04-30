-- SQL Server setup script for pricing retrieval
-- Creates:
--   dbo.material_prices
--   dbo.labour_rates
-- Seeds starter rows
-- Provides quick validation queries

SET NOCOUNT ON;
GO

-- =========================================================
-- 1) TABLES
-- =========================================================
IF OBJECT_ID('dbo.material_prices', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.material_prices (
        material_price_id      bigint IDENTITY(1,1) PRIMARY KEY,
        material_code          nvarchar(100) NOT NULL,
        thickness_mm           decimal(10,3) NULL,
        price_gbp_per_kg       decimal(18,6) NOT NULL,
        supplier_code          nvarchar(50) NULL,
        supplier_name          nvarchar(255) NULL,
        effective_date         date NOT NULL,
        expires_date           date NULL,
        is_active              bit NOT NULL CONSTRAINT DF_material_prices_is_active DEFAULT (1),
        source_note            nvarchar(500) NULL,
        created_at             datetime2(0) NOT NULL CONSTRAINT DF_material_prices_created_at DEFAULT (sysdatetime())
    );

    CREATE INDEX IX_material_prices_lookup
        ON dbo.material_prices (material_code, is_active, effective_date DESC)
        INCLUDE (thickness_mm, price_gbp_per_kg, supplier_name, supplier_code);

    CREATE INDEX IX_material_prices_thickness
        ON dbo.material_prices (material_code, thickness_mm, effective_date DESC)
        INCLUDE (price_gbp_per_kg, is_active, supplier_name, supplier_code);
END;
GO

IF OBJECT_ID('dbo.labour_rates', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.labour_rates (
        labour_rate_id         bigint IDENTITY(1,1) PRIMARY KEY,
        operation_code         nvarchar(50) NOT NULL,
        hourly_rate_gbp        decimal(18,4) NOT NULL,
        department_code        nvarchar(50) NULL,
        effective_date         date NOT NULL,
        expires_date           date NULL,
        is_active              bit NOT NULL CONSTRAINT DF_labour_rates_is_active DEFAULT (1),
        source_note            nvarchar(500) NULL,
        created_at             datetime2(0) NOT NULL CONSTRAINT DF_labour_rates_created_at DEFAULT (sysdatetime())
    );

    CREATE INDEX IX_labour_rates_lookup
        ON dbo.labour_rates (operation_code, is_active, effective_date DESC)
        INCLUDE (hourly_rate_gbp, department_code);
END;
GO

-- =========================================================
-- 2) SEED DATA (safe insert: only if not already present)
-- =========================================================
IF NOT EXISTS (SELECT 1 FROM dbo.material_prices)
BEGIN
    INSERT INTO dbo.material_prices
    (
        material_code,
        thickness_mm,
        price_gbp_per_kg,
        supplier_code,
        supplier_name,
        effective_date,
        expires_date,
        is_active,
        source_note
    )
    VALUES
    ('MILD_STEEL', 0.9, 1.25, 'SUP001', 'Example Steel Ltd', '2026-01-01', NULL, 1, 'Starter seed'),
    ('MILD_STEEL', 1.0, 1.28, 'SUP001', 'Example Steel Ltd', '2026-01-01', NULL, 1, 'Starter seed'),
    ('MILD_STEEL', 1.2, 1.31, 'SUP001', 'Example Steel Ltd', '2026-01-01', NULL, 1, 'Starter seed'),
    ('MILD_STEEL', 1.5, 1.36, 'SUP001', 'Example Steel Ltd', '2026-01-01', NULL, 1, 'Starter seed'),
    ('MILD_STEEL', 2.0, 1.45, 'SUP001', 'Example Steel Ltd', '2026-01-01', NULL, 1, 'Starter seed'),
    ('STAINLESS_STEEL', 1.0, 3.10, 'SUP002', 'Stainless Supply Co', '2026-01-01', NULL, 1, 'Starter seed'),
    ('STAINLESS_STEEL', 1.5, 3.45, 'SUP002', 'Stainless Supply Co', '2026-01-01', NULL, 1, 'Starter seed'),
    ('ALUMINIUM', 1.0, 2.75, 'SUP003', 'Alu Metals UK', '2026-01-01', NULL, 1, 'Starter seed'),
    ('ALUMINIUM', 1.5, 2.95, 'SUP003', 'Alu Metals UK', '2026-01-01', NULL, 1, 'Starter seed');
END;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.labour_rates)
BEGIN
    INSERT INTO dbo.labour_rates
    (
        operation_code,
        hourly_rate_gbp,
        department_code,
        effective_date,
        expires_date,
        is_active,
        source_note
    )
    VALUES
    ('laser_cutting', 68.19, 'LASM', '2026-01-01', NULL, 1, 'From estimate template'),
    ('folding', 40.47, 'FOLD', '2026-01-01', NULL, 1, 'From estimate template'),
    ('powder_coating', 355.43, 'P/C', '2026-01-01', NULL, 1, 'From estimate template'),
    ('handling', 31.18, 'MANM', '2026-01-01', NULL, 1, 'From estimate template'),
    ('assembly', 28.56, 'PACM', '2026-01-01', NULL, 1, 'From estimate template');
END;
GO

-- =========================================================
-- 3) VALIDATION / SMOKE TESTS
-- =========================================================
SELECT TOP (10) *
FROM dbo.material_prices
ORDER BY effective_date DESC, material_price_id DESC;

SELECT TOP (10) *
FROM dbo.labour_rates
ORDER BY effective_date DESC, labour_rate_id DESC;

-- Example material lookup equivalent to app behavior:
DECLARE @material nvarchar(100) = N'MILD_STEEL';
DECLARE @thickness decimal(10,3) = 1.0;

SELECT TOP (1)
    mp.material_code AS material,
    mp.thickness_mm,
    mp.price_gbp_per_kg AS price,
    'GBP' AS currency,
    'GBP_per_kg' AS unit,
    0.95 AS confidence,
    COALESCE(mp.supplier_name, mp.supplier_code, 'material_prices') AS supplier_source,
    mp.effective_date AS price_date
FROM dbo.material_prices mp
WHERE UPPER(LTRIM(RTRIM(mp.material_code))) = UPPER(LTRIM(RTRIM(@material)))
  AND mp.is_active = 1
  AND mp.effective_date <= CAST(GETDATE() AS date)
  AND (mp.expires_date IS NULL OR mp.expires_date >= CAST(GETDATE() AS date))
  AND (mp.thickness_mm IS NULL OR ABS(mp.thickness_mm - @thickness) <= 0.15)
ORDER BY
    CASE WHEN mp.thickness_mm IS NULL THEN 1 ELSE 0 END,
    ABS(COALESCE(mp.thickness_mm, @thickness) - @thickness),
    mp.effective_date DESC;

-- Example labour lookup equivalent to app behavior:
DECLARE @op nvarchar(50) = N'folding';

SELECT TOP (1)
    lr.operation_code AS rate_code,
    lr.hourly_rate_gbp AS price,
    'GBP' AS currency,
    'GBP_per_hour' AS unit,
    0.95 AS confidence,
    lr.effective_date AS price_date
FROM dbo.labour_rates lr
WHERE LOWER(LTRIM(RTRIM(lr.operation_code))) = LOWER(LTRIM(RTRIM(@op)))
  AND lr.is_active = 1
  AND lr.effective_date <= CAST(GETDATE() AS date)
  AND (lr.expires_date IS NULL OR lr.expires_date >= CAST(GETDATE() AS date))
ORDER BY lr.effective_date DESC;
GO

