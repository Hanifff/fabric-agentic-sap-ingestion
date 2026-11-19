# Copilot instructions

This repository is a ready-made workspace for **AI-assisted Microsoft Fabric development from VS Code**: GitHub Copilot in agent mode, the Fabric MCP server and the Fabric skills, used to build **Data Factory pipelines** for a **metadata-driven SAP S/4HANA ingestion framework** (landing files to bronze tables, controlled from a warehouse). The company (Contoso Drilling Systems) and all data are fictional and synthetic.

Do not start from scratch. Once the setup in `README.md` has been run, the Fabric environment, landing data, control layer and conventions already exist. Before acting, read this file, `environment/fabric-environment.json` and the relevant document in `docs/`.

## Environment

`environment/fabric-environment.json` is the single source of truth for IDs and endpoints. `python scripts/fabric_env.py provision` writes it. If it is missing, stop and ask the user to run the setup first. Never guess or invent IDs, connection strings or paths, and never use the placeholder values in `fabric-environment.example.json`.

| What | Keys in the environment file | Notes |
|---|---|---|
| Tenant | `tenantId` | |
| Capacity | `capacity.name`, `capacity.id` | Usually small and possibly shared, so keep consumption low |
| Workspace | `workspace.name`, `workspace.id` | Default name `Agentic SAP Demo - DEV`. This is the only workspace you may change |
| Lakehouse | `lakehouse.*` (`lh_bronze`) | Landing files under `Files/landing` and bronze Delta tables. Schemas are not enabled, so tables appear as `dbo.<table>` in SQL |
| Warehouse | `warehouse.*` (`wh_control`) | Schema `ctl`: ingestion config, watermarks, run log, stored procedures |

## Guardrails

1. **Read before you write.** Inspect state with the `fabricReadOnly` MCP server. It runs with `--read-only`, so it has no write tools.
2. **Write only to the workspace in the environment file, and only through the `fabricDevWrite` MCP server.** That server exposes six tools: `core_create-item`, `core_get-item-definition`, `core_update-item-definition`, `jobs_run-on-demand-item-job`, `jobs_get-item-job-instance` and `jobs_cancel-item-job-instance`. Before the first write in a session, state which items you will create or change.
3. **Git first.** Write every item definition to the repo before deploying it, in Fabric Git format: `fabric/<name>.DataPipeline/pipeline-content.json` plus `.platform`. Deploy from those files with `definition-directory`, so the repo and the workspace never drift.
4. **Never** delete items, change role assignments, the capacity or workspace settings, or modify `lh_bronze`, `wh_control` or the landing files. Run `scripts/fabric_env.py reset` only when the user asks. Ignore the `fallback` branch unless the user asks for it.
5. **Keep consumption low.**
   - Use pipelines with Copy and stored-procedure activities.
   - Don't use Spark notebooks unless asked.
   - Don't rerun a load that already succeeded.
   - Poll job status every 30–60 seconds.
6. **No secrets.** Authentication is the signed-in Azure CLI identity. Never write tokens or keys to files.

## Ingestion framework

Full details are in `docs/design/ingestion-framework.md`.

- **Landing.** In `lh_bronze`, files are at `Files/landing/sap_s4/<TABLE>/load_date=YYYY-MM-DD/<TABLE>_YYYYMMDD.csv`: CSV with a header row, comma-separated, UTF-8. There are 10 SAP tables with load dates 2026-11-12 to 2026-11-18.
- **Control.** Schema `ctl` in `wh_control` holds:
  - `ingestion_config`: what to load and how.
  - `watermark` and `run_log`: both append-only.
  - Views `v_watermark` and `v_run_status`.
  - Procedures `usp_get_objects_to_load`, `usp_log_run_start` and `usp_log_run_end`.
- **Bronze.** Tables in `lh_bronze` are named `sap_s4_<table>`.
  - FULL objects are overwritten and INCREMENTAL objects are appended.
  - Source columns stay as strings.
  - Each table gets the lineage columns `_LOAD_DATE`, `_SOURCE_FILE` and `_PIPELINE_RUN_ID`.
- **Pipelines.**
  - `pl_bronze_sap_child` loads one object.
  - `pl_bronze_sap_master` looks up the objects to load and runs the child for each one (ForEach, batch count 4).
  - Keep it to two levels.
- **Pipeline JSON.** Rules and validated snippets are in `.github/instructions/fabric-pipelines.instructions.md`. Naming and layer rules are in `docs/standards/`.
- **Skills.** If the Fabric skills are installed, use them. `pipeline-migration` covers converting Synapse/ADF pipeline JSON and `e2e-medallion-architecture` covers layer design.

## Common tasks

| Task | How |
|---|---|
| List items and pipelines | `fabricReadOnly`: `core_list-items`, `datafactory_list-pipelines` |
| List landing files | `fabricReadOnly`: `onelake_list-files` with the workspace ID, lakehouse ID and path `Files/landing/sap_s4` |
| Query control tables | Terminal: `python scripts/fabric_env.py sql "SELECT * FROM ctl.v_run_status ORDER BY started_at DESC"` |
| Query bronze tables | Terminal: `python scripts/fabric_env.py sql --target lakehouse "SELECT COUNT(*) FROM dbo.sap_s4_mara"`. This refreshes the SQL endpoint metadata first; otherwise counts can be stale after a load |
| Check the item definition format | `fabricReadOnly`: `docs_item-definitions` for DataPipeline, plus the pipeline instructions file |
| Create a pipeline | `fabricDevWrite`: `core_create-item` with `workspace-id`, `display-name`, `item-type` `DataPipeline`, `definition-directory` set to the absolute path of `fabric/<name>.DataPipeline`, `definition-files` set to `[{"partPath":"pipeline-content.json","sourcePath":"pipeline-content.json"}]`, and `sync` true |
| Update a pipeline | `fabricDevWrite`: `core_update-item-definition` with the same `definition-directory` and `definition-files` |
| Run with parameters | `fabricDevWrite`: `jobs_run-on-demand-item-job` with `job-type` `Pipeline` and `execution-data` `{"parameters":{"p_load_date":"2026-11-12","p_load_group":"ALL"}}`. The user must approve the run |
| Monitor a run | `jobs_get-item-job-instance` (first check after about 60 seconds), then query `ctl.v_run_status` for each object |
| CLI fallback | `python scripts/fabric_env.py status`, `deploy <folder>`, `run <pipeline> -p name=value` |

## Working style

- Explain the plan in a few lines, then work in small, verifiable steps.
- When a run fails:
  1. Read the job `failureReason` and `ctl.v_run_status.error_message`.
  2. Fix the JSON in the repo.
  3. Update the item and rerun only what failed.
- When done, report the items created or changed with their IDs, the run IDs, row counts per object and anything that needs a human decision.

## Definition of done for pipeline work

- The JSON is valid, follows the pipeline instructions, and uses IDs and endpoints from `environment/fabric-environment.json`.
- The item was created or updated in the DEV workspace from the repo folder and opens in the Fabric UI.
- The run for the requested load date completed.
- `ctl.v_run_status` shows Succeeded for every object.
- Bronze row counts match the landing files for that date.
