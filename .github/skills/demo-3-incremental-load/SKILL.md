---
name: demo-3-incremental-load
description: Run the next daily bronze load (2026-11-13) and prove FULL overwrite vs INCREMENTAL append behaviour, rerun safety and watermarks.
disable-model-invocation: true
---
# Incremental load

1. Run `pl_bronze_sap_master` for `p_load_date` = `2026-11-13` and monitor it until it finishes.
2. For each bronze table, show the row count and the `_LOAD_DATE` values present.
   - FULL tables should contain only 2026-11-13.
   - INCREMENTAL tables should contain 2026-11-12 and 2026-11-13.
3. Without running anything, explain what a rerun of 2026-11-13 would load, and why. Use `EXEC ctl.usp_get_objects_to_load @load_group = 'ALL', @load_date = '2026-11-13'`.
4. Show `ctl.v_watermark`.
