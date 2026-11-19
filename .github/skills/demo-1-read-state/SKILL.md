---
name: demo-1-read-state
description: Read-only status of the Fabric DEV workspace and the SAP bronze ingestion framework - items, landing data, control tables and the IDs a pipeline needs. Changes nothing. Use at the start of a session or when asked for the current state.
disable-model-invocation: true
---
# Read the current state (read-only)

Use only read-only tools: the `fabricReadOnly` MCP server and `python scripts/fabric_env.py sql ...`. Do not create, change or run anything.

1. Workspace from `environment/fabric-environment.json`: list the items by type and say whether any pipelines exist yet.
2. Landing data in `lh_bronze` under `Files/landing/sap_s4`: which SAP tables and which load dates are available.
3. Control layer in `wh_control`: active objects per load group and load type (`ctl.ingestion_config`), current watermarks (`ctl.v_watermark`) and recent runs (`ctl.v_run_status`).
4. What is missing to load bronze for 2026-11-12, and which IDs and endpoints a pipeline will need. Take them from `environment/fabric-environment.json` and cross-check them against the workspace.

End with a summary of no more than five lines.
