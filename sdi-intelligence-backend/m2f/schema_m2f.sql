-- SDI Monday2Friday: account and delivery records (SQL Server, SDILive).
-- Run in SSMS, or with m2f.db_load.apply_schema() which splits on GO lines.
-- Safe to re-run: every object is created only if it does not exist yet.
-- Comments stay plain double-dash: decorated separators break pyodbc DDL.

IF SCHEMA_ID('m2f') IS NULL EXEC('CREATE SCHEMA m2f');
GO

-- People: AMs, PMs, director, finance, and the studio, technical and estimating teams.
IF OBJECT_ID('m2f.person') IS NULL
CREATE TABLE m2f.person (
    person_id        INT IDENTITY PRIMARY KEY,
    display_name     NVARCHAR(100) NOT NULL,
    role             NVARCHAR(20)  NOT NULL
        CHECK (role IN ('Director', 'AM', 'PM', 'Finance', 'Studio', 'Technical', 'Estimating', 'Other')),
    email            NVARCHAR(200) NULL,
    deputy_person_id INT NULL REFERENCES m2f.person (person_id),
    is_active        BIT NOT NULL DEFAULT 1
);
GO

-- Every spelling used in the tracker's PM and AM columns, mapped to one person once confirmed.
IF OBJECT_ID('m2f.person_alias') IS NULL
CREATE TABLE m2f.person_alias (
    alias     NVARCHAR(100) NOT NULL PRIMARY KEY,
    person_id INT NOT NULL REFERENCES m2f.person (person_id)
);
GO

-- Accounts: Boots is the parent of Boots UK, Sigma, Boots Opticians and Boots Hearingcare.
IF OBJECT_ID('m2f.account') IS NULL
CREATE TABLE m2f.account (
    account_id         INT IDENTITY PRIMARY KEY,
    name               NVARCHAR(150) NOT NULL UNIQUE,
    parent_account_id  INT NULL REFERENCES m2f.account (account_id),
    segment            NVARCHAR(50)  NOT NULL,
    owner_person_id    INT NULL REFERENCES m2f.person (person_id),
    sage_customer_code NVARCHAR(20)  NULL,
    is_active          BIT NOT NULL DEFAULT 1
);
GO

IF OBJECT_ID('m2f.project') IS NULL
CREATE TABLE m2f.project (
    project_id      INT IDENTITY PRIMARY KEY,
    account_id      INT NOT NULL REFERENCES m2f.account (account_id),
    name            NVARCHAR(300) NOT NULL,
    lifecycle       NVARCHAR(20)  NOT NULL DEFAULT 'live'
        CHECK (lifecycle IN ('live', 'bid', 'archive')),
    stage           NVARCHAR(40)  NULL,
    am_person_id    INT NULL REFERENCES m2f.person (person_id),
    pm_person_id    INT NULL REFERENCES m2f.person (person_id),
    project_code    NVARCHAR(30)  NULL,
    sales_order     NVARCHAR(200) NULL,
    po_ref          NVARCHAR(200) NULL,
    drawing         NVARCHAR(200) NULL,
    contact         NVARCHAR(200) NULL,
    next_step       NVARCHAR(MAX) NULL,
    next_action_due DATE NULL,
    sell_value      DECIMAL(18, 2) NULL,
    cost_value      DECIMAL(18, 2) NULL,
    margin_pct      DECIMAL(9, 4)  NULL,
    notes           NVARCHAR(MAX) NULL,
    source_key      NVARCHAR(20)  NULL,     -- tracker tab code and row at import, e.g. BUK-004
    created_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_by      NVARCHAR(100) NULL
);
GO

-- The tracker's four statuses. mockup_column is how each shows on the dashboards
-- (Invoiced, PO received, Awaiting PO, At risk): Kayleigh confirms the mapping.
IF OBJECT_ID('m2f.forecast_status') IS NULL
BEGIN
    CREATE TABLE m2f.forecast_status (
        status        NVARCHAR(20) NOT NULL PRIMARY KEY,
        sort_order    TINYINT NOT NULL,
        mockup_column NVARCHAR(30) NULL
    );
    INSERT m2f.forecast_status (status, sort_order, mockup_column) VALUES
        ('Invoiced', 1, 'Invoiced'), ('Confirmed', 2, NULL), ('TBC', 3, NULL), ('Risk', 4, 'At risk');
END;
GO

-- One row per project per month. A line can be dated and valued but not yet classified.
IF OBJECT_ID('m2f.forecast_line') IS NULL
CREATE TABLE m2f.forecast_line (
    line_id          BIGINT IDENTITY PRIMARY KEY,
    project_id       INT NOT NULL REFERENCES m2f.project (project_id),
    period_month     DATE NOT NULL CHECK (DAY(period_month) = 1),
    amount           DECIMAL(18, 2) NOT NULL,
    status           NVARCHAR(20) NULL REFERENCES m2f.forecast_status (status),
    status_source    NVARCHAR(10) NOT NULL DEFAULT 'manual'
        CHECK (status_source IN ('legend', 'manual', 'sage')),
    sage_invoice_ref NVARCHAR(50) NULL,
    reason           NVARCHAR(300) NULL,    -- why it last moved, shown on the weekly review
    updated_at       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_by       NVARCHAR(100) NULL,
    CONSTRAINT uq_forecast_line UNIQUE (project_id, period_month)
);
GO

-- Forecast freeze: a copy of every line at the moment of the freeze, so the
-- weekly review can show what moved since, by how much and why.
IF OBJECT_ID('m2f.forecast_freeze') IS NULL
CREATE TABLE m2f.forecast_freeze (
    freeze_id INT IDENTITY PRIMARY KEY,
    label     NVARCHAR(100) NOT NULL,
    frozen_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    frozen_by NVARCHAR(100) NULL
);
GO

IF OBJECT_ID('m2f.forecast_freeze_line') IS NULL
CREATE TABLE m2f.forecast_freeze_line (
    freeze_id    INT NOT NULL REFERENCES m2f.forecast_freeze (freeze_id),
    line_id      BIGINT NOT NULL,
    project_id   INT NOT NULL,
    period_month DATE NOT NULL,
    amount       DECIMAL(18, 2) NOT NULL,
    status       NVARCHAR(20) NULL,
    PRIMARY KEY (freeze_id, line_id)
);
GO

IF OBJECT_ID('m2f.budget') IS NULL
CREATE TABLE m2f.budget (
    account_id   INT NOT NULL REFERENCES m2f.account (account_id),
    period_month DATE NOT NULL CHECK (DAY(period_month) = 1),
    amount       DECIMAL(18, 2) NOT NULL,
    PRIMARY KEY (account_id, period_month)
);
GO

-- Changes to agreed scope: what changed, its commercial and CPA impact, and who acts next.
IF OBJECT_ID('m2f.variation') IS NULL
CREATE TABLE m2f.variation (
    variation_id    INT IDENTITY PRIMARY KEY,
    project_id      INT NOT NULL REFERENCES m2f.project (project_id),
    title           NVARCHAR(200) NOT NULL,
    sell_value      DECIMAL(18, 2) NULL,
    margin_pct      DECIMAL(9, 4)  NULL,
    cpa_impact      NVARCHAR(300) NULL,
    approval_status NVARCHAR(20) NOT NULL DEFAULT 'To price'
        CHECK (approval_status IN ('To price', 'Awaiting PO', 'Decision needed', 'Approved', 'Rejected')),
    po_ref          NVARCHAR(50) NULL,
    owner_person_id INT NULL REFERENCES m2f.person (person_id),
    next_action     NVARCHAR(300) NULL,
    due_date        DATE NULL,
    created_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    created_by      NVARCHAR(100) NULL
);
GO

-- Notes, calls, meetings, emails and next actions against an account or project.
IF OBJECT_ID('m2f.activity') IS NULL
CREATE TABLE m2f.activity (
    activity_id     BIGINT IDENTITY PRIMARY KEY,
    account_id      INT NULL REFERENCES m2f.account (account_id),
    project_id      INT NULL REFERENCES m2f.project (project_id),
    kind            NVARCHAR(10) NOT NULL CHECK (kind IN ('note', 'call', 'meeting', 'email', 'action')),
    body            NVARCHAR(MAX) NOT NULL,
    due_date        DATE NULL,
    done_at         DATETIME2 NULL,
    owner_person_id INT NULL REFERENCES m2f.person (person_id),
    created_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    created_by      NVARCHAR(100) NULL,
    CHECK (account_id IS NOT NULL OR project_id IS NOT NULL)
);
GO

-- Import staging: each tracker import lands here untouched, with its issues.
-- Rows move to the live tables only after the review decisions are made.
IF OBJECT_ID('m2f.import_batch') IS NULL
CREATE TABLE m2f.import_batch (
    batch_id     INT IDENTITY PRIMARY KEY,
    source_file  NVARCHAR(260) NOT NULL,
    imported_at  DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    imported_by  NVARCHAR(100) NULL,
    summary_json NVARCHAR(MAX) NULL
);
GO

IF OBJECT_ID('m2f.import_issue') IS NULL
CREATE TABLE m2f.import_issue (
    issue_id    BIGINT IDENTITY PRIMARY KEY,
    batch_id    INT NOT NULL REFERENCES m2f.import_batch (batch_id),
    code        NVARCHAR(50) NOT NULL,
    severity    NVARCHAR(10) NOT NULL CHECK (severity IN ('decision', 'check', 'info')),
    message     NVARCHAR(1000) NOT NULL,
    tab         NVARCHAR(100) NULL,
    cell        NVARCHAR(20) NULL,
    source_key  NVARCHAR(20) NULL,
    resolved_at DATETIME2 NULL,
    resolved_by NVARCHAR(100) NULL,
    resolution  NVARCHAR(500) NULL
);
GO

IF OBJECT_ID('m2f.stg_project') IS NULL
CREATE TABLE m2f.stg_project (
    batch_id    INT NOT NULL REFERENCES m2f.import_batch (batch_id),
    source_key  NVARCHAR(20) NOT NULL,
    tab         NVARCHAR(100) NOT NULL,
    source_row  INT NOT NULL,
    hidden      BIT NOT NULL,
    segment     NVARCHAR(50) NOT NULL,
    account     NVARCHAR(150) NOT NULL,
    name        NVARCHAR(300) NOT NULL,
    fields_json NVARCHAR(MAX) NULL,
    extra_json  NVARCHAR(MAX) NULL,
    PRIMARY KEY (batch_id, source_key)
);
GO

IF OBJECT_ID('m2f.stg_forecast_line') IS NULL
CREATE TABLE m2f.stg_forecast_line (
    batch_id     INT NOT NULL REFERENCES m2f.import_batch (batch_id),
    source_key   NVARCHAR(20) NOT NULL,
    tab          NVARCHAR(100) NOT NULL,
    cell         NVARCHAR(20) NOT NULL,
    period_month DATE NULL,
    amount       DECIMAL(18, 2) NULL,
    raw          NVARCHAR(100) NOT NULL,
    value_type   NVARCHAR(20) NOT NULL,
    status       NVARCHAR(20) NULL,
    fill         NVARCHAR(30) NOT NULL,
    PRIMARY KEY (batch_id, tab, cell)
);
GO

-- Forecast by account, month and status: the source for the dashboard tiles.
CREATE OR ALTER VIEW m2f.v_forecast_month AS
SELECT a.account_id, a.name AS account, pa.name AS parent_account,
       fl.period_month, ISNULL(fl.status, 'Unclassified') AS status,
       SUM(fl.amount) AS amount, COUNT(*) AS lines
FROM m2f.forecast_line fl
JOIN m2f.project p ON p.project_id = fl.project_id AND p.lifecycle <> 'archive'
JOIN m2f.account a ON a.account_id = p.account_id
LEFT JOIN m2f.account pa ON pa.account_id = a.parent_account_id
GROUP BY a.account_id, a.name, pa.name, fl.period_month, ISNULL(fl.status, 'Unclassified');
GO
