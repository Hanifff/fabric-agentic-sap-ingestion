# Bronze layer rules

1. **Source fidelity.** Keep SAP field names and values exactly as extracted. All source columns are strings, so leading zeros (`MATNR`) and `YYYYMMDD` dates survive unchanged. Types and business names belong in silver.
2. **No business logic.** Bronze has no filtering, joins, deduplication or derived columns. The only exception is the technical lineage columns.
3. **Lineage on every row.**
   - `_LOAD_DATE`: the landing partition.
   - `_SOURCE_FILE`: the file the row came from.
   - `_PIPELINE_RUN_ID`: the child pipeline run.
4. **Load types.**
   - FULL objects are overwritten with the latest snapshot.
   - INCREMENTAL objects are appended, including `ODQ_CHANGEMODE`. Deduplication to the latest version per business key happens in silver.
5. **Logging.** Every object load writes a `Started` event and a `Succeeded` or `Failed` event to `ctl.run_log`. A load advances the watermark only when it succeeds.
6. **Idempotent reruns.** Rerunning a load date must not duplicate incremental data; `ctl.usp_get_objects_to_load` enforces this.
7. **Landing is read-only.** Pipelines never modify or delete landing files.
8. **Control writes are INSERT-only.** Child pipelines run in parallel, and Fabric Warehouse aborts concurrent UPDATEs on the same table.
