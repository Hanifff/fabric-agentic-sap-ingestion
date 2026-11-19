---
name: demo-4-catchup
description: Stretch goal - add a catch-up pipeline (pl_bronze_sap_catchup) that loads a range of dates in order by calling the existing master pipeline, then deploy, run and verify it.
disable-model-invocation: true
---
# Catch-up pipeline (stretch)

Missed days currently have to be run one by one. Add a catch-up pipeline that loads a range of dates in order:

1. **Design `pl_bronze_sap_catchup`.**
   - Parameters: `p_from_date`, `p_to_date` and `p_load_group` (default `ALL`).
   - Build the list of dates between the two parameters with pipeline expressions; `range()` and `addDays()` are fine.
   - A sequential ForEach runs the existing `pl_bronze_sap_master` once per date, waiting for each run to finish.
   - Don't change the existing pipelines. Show the plan first.
2. Write it under `fabric/`, deploy it to DEV with the `fabricDevWrite` tools, and run it for 2026-11-14 to 2026-11-16.
3. Verify the watermarks and `ctl.v_run_status`. Then explain why the weekend days (14 and 15 November) loaded few or no transaction rows.
