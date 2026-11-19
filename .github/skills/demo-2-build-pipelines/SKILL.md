---
name: demo-2-build-pipelines
description: Build, deploy and run the metadata-driven bronze ingestion pipelines (pl_bronze_sap_child and pl_bronze_sap_master) in the Fabric DEV workspace, Git first, then verify the load against the control tables and landing files.
disable-model-invocation: true
---
# Build the bronze ingestion pipelines

Build the pipelines described in `docs/design/ingestion-framework.md`. Follow `.github/instructions/fabric-pipelines.instructions.md` and the standards in `docs/standards/`.

1. **Plan.** List the activities, parameters and dependencies of `pl_bronze_sap_child` and `pl_bronze_sap_master`. Keep it short, then wait for the user's OK.
2. **Write.** Save both definitions under `fabric/` in Fabric Git format (`pipeline-content.json` + `.platform`), using the real IDs from `environment/fabric-environment.json`. Validate the JSON.
3. **Deploy** to the DEV workspace with the `fabricDevWrite` tools, from those folders:
   1. Create the child first.
   2. Put the child's item ID into the master's ExecutePipeline activity.
   3. Create the master.
4. **Run** `pl_bronze_sap_master` with `p_load_date` = `2026-11-12` and `p_load_group` = `ALL`. The user approves the run. Monitor it until it finishes.
5. **Verify.**
   - Every object shows Succeeded in `ctl.v_run_status`.
   - Bronze row counts match the landing files for that date.
   - If anything failed: read the error, fix the JSON in the repo, update the item and rerun.

Report the item IDs, run ID and duration, plus a table of rows per object.
