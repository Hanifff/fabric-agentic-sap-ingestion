-- Stored procedures used by the ingestion pipelines. Pipelines call these instead of
-- running Spark just to read config or write audit rows. All writes are INSERTs, so
-- child pipelines can run in parallel without update conflicts.

CREATE OR ALTER PROCEDURE ctl.usp_get_objects_to_load
    @load_group varchar(50),   -- SAP_MASTERDATA | SAP_TRANSACTIONS | ALL
    @load_date  date           -- landing partition to load (load_date=YYYY-MM-DD)
AS
BEGIN
    SET NOCOUNT ON;

    SELECT c.source_system,
           c.source_object,
           c.load_type,
           c.target_table,
           CONCAT(c.landing_folder, '/load_date=', CONVERT(varchar(10), @load_date, 23)) AS landing_path,
           CASE WHEN c.load_type = 'FULL' THEN 'Overwrite' ELSE 'Append' END        AS table_action,
           CONVERT(varchar(10), @load_date, 23)                                      AS load_date
    FROM ctl.ingestion_config AS c
    LEFT JOIN ctl.v_watermark AS w
           ON w.source_system = c.source_system
          AND w.source_object = c.source_object
    WHERE c.is_active = 1
      AND (@load_group = 'ALL' OR c.load_group = @load_group)
      -- Rerun-safe: skip incremental objects whose watermark already covers this load date.
      AND NOT (c.load_type = 'INCREMENTAL' AND w.last_load_date IS NOT NULL AND w.last_load_date >= @load_date)
    ORDER BY c.priority, c.source_object;
END
GO

CREATE OR ALTER PROCEDURE ctl.usp_log_run_start
    @pipeline_run_id varchar(64),
    @parent_run_id   varchar(64),
    @pipeline_name   varchar(200),
    @source_system   varchar(20),
    @source_object   varchar(50),
    @load_date       date
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO ctl.run_log (pipeline_run_id, parent_run_id, pipeline_name, source_system, source_object,
                             load_date, event, rows_copied, error_message, logged_at)
    VALUES (@pipeline_run_id, NULLIF(@parent_run_id, ''), @pipeline_name, @source_system, @source_object,
            @load_date, 'Started', NULL, NULL, SYSUTCDATETIME());
END
GO

CREATE OR ALTER PROCEDURE ctl.usp_log_run_end
    @pipeline_run_id varchar(64),
    @pipeline_name   varchar(200),
    @source_system   varchar(20),
    @source_object   varchar(50),
    @load_date       date,
    @status          varchar(20),          -- Succeeded | Failed
    @rows_copied     bigint        = NULL,
    @error_message   varchar(4000) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO ctl.run_log (pipeline_run_id, parent_run_id, pipeline_name, source_system, source_object,
                             load_date, event, rows_copied, error_message, logged_at)
    VALUES (@pipeline_run_id, NULL, @pipeline_name, @source_system, @source_object,
            @load_date, @status, @rows_copied, LEFT(@error_message, 4000), SYSUTCDATETIME());

    IF @status = 'Succeeded'
        INSERT INTO ctl.watermark (source_system, source_object, load_date, rows_copied, pipeline_run_id, loaded_at)
        VALUES (@source_system, @source_object, @load_date, @rows_copied, @pipeline_run_id, SYSUTCDATETIME());
END
GO
