-- Control objects for the metadata-driven SAP ingestion framework (Fabric Warehouse wh_control).
-- Idempotent: safe to run more than once.
--
-- Fabric Warehouse notes:
--   * Concurrent UPDATE/DELETE on the same table conflict (snapshot isolation, table-level
--     detection). Child pipelines run in parallel, so run_log and watermark are append-only
--     and the "current" state is exposed through views.
--   * No nvarchar, no DEFAULT constraints, datetime2 precision max 6.

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'ctl')
    EXEC('CREATE SCHEMA ctl');
GO

IF OBJECT_ID('ctl.ingestion_config') IS NULL
BEGIN
    CREATE TABLE ctl.ingestion_config (
        source_system      varchar(20)  NOT NULL,  -- e.g. SAP_S4
        source_object      varchar(50)  NOT NULL,  -- SAP table, e.g. MARA
        object_description varchar(200) NULL,
        load_group         varchar(50)  NOT NULL,  -- SAP_MASTERDATA | SAP_TRANSACTIONS
        load_type          varchar(20)  NOT NULL,  -- FULL | INCREMENTAL
        business_key       varchar(200) NULL,      -- comma-separated SAP key fields
        watermark_column   varchar(50)  NULL,      -- load_date (landing folder partition) for INCREMENTAL
        landing_folder     varchar(400) NOT NULL,  -- relative to lh_bronze Files/, e.g. landing/sap_s4/MARA
        target_table       varchar(128) NOT NULL,  -- bronze Delta table in lh_bronze, e.g. sap_s4_mara
        priority           int          NOT NULL,
        is_active          bit          NOT NULL
    );
END
GO

-- One row per successful load (append-only). Latest row per object = current watermark.
IF OBJECT_ID('ctl.watermark') IS NULL
BEGIN
    CREATE TABLE ctl.watermark (
        source_system   varchar(20)  NOT NULL,
        source_object   varchar(50)  NOT NULL,
        load_date       date         NOT NULL,
        rows_copied     bigint       NULL,
        pipeline_run_id varchar(64)  NULL,
        loaded_at       datetime2(6) NOT NULL
    );
END
GO

-- Run events (append-only): one 'Started' row and one 'Succeeded' or 'Failed' row per child run.
IF OBJECT_ID('ctl.run_log') IS NULL
BEGIN
    CREATE TABLE ctl.run_log (
        pipeline_run_id varchar(64)   NOT NULL,
        parent_run_id   varchar(64)   NULL,
        pipeline_name   varchar(200)  NOT NULL,
        source_system   varchar(20)   NULL,
        source_object   varchar(50)   NULL,
        load_date       date          NULL,
        event           varchar(20)   NOT NULL,  -- Started | Succeeded | Failed
        rows_copied     bigint        NULL,
        error_message   varchar(4000) NULL,
        logged_at       datetime2(6)  NOT NULL
    );
END
GO

CREATE OR ALTER VIEW ctl.v_watermark AS
SELECT source_system,
       source_object,
       load_date       AS last_load_date,
       rows_copied     AS last_rows_copied,
       pipeline_run_id AS last_pipeline_run_id,
       loaded_at
FROM (
    SELECT w.*,
           ROW_NUMBER() OVER (PARTITION BY w.source_system, w.source_object
                              ORDER BY w.load_date DESC, w.loaded_at DESC) AS rn
    FROM ctl.watermark AS w
) AS latest
WHERE rn = 1;
GO

CREATE OR ALTER VIEW ctl.v_run_status AS
SELECT s.pipeline_run_id,
       s.parent_run_id,
       s.pipeline_name,
       s.source_system,
       s.source_object,
       s.load_date,
       COALESCE(e.event, 'Running')                 AS status,
       e.rows_copied,
       e.error_message,
       s.logged_at                                  AS started_at,
       e.logged_at                                  AS ended_at,
       DATEDIFF(second, s.logged_at, e.logged_at)   AS duration_seconds
FROM ctl.run_log AS s
LEFT JOIN ctl.run_log AS e
       ON e.pipeline_run_id = s.pipeline_run_id
      AND e.source_object   = s.source_object
      AND e.event IN ('Succeeded', 'Failed')
WHERE s.event = 'Started';
GO
