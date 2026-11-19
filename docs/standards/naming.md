# Naming standards

| Object | Pattern | Example |
|---|---|---|
| Workspace | `<Domain> - <ENV>` | `Agentic SAP Demo - DEV` |
| Lakehouse | `lh_<layer>` | `lh_bronze` |
| Warehouse | `wh_<purpose>` | `wh_control` |
| Pipeline | `pl_<layer>_<source>_<role>` | `pl_bronze_sap_master`, `pl_bronze_sap_child` |
| Notebook | `nb_<layer>_<subject>` | `nb_silver_purchase_orders` |
| Variable library | `vl_<scope>` | `vl_ingestion` |
| Bronze table | `<source_system>_<object>`, lowercase | `sap_s4_mara` |
| Pipeline parameter | `p_<name>` | `p_load_date` |
| Pipeline variable | `v_<name>` | `v_load_date` |
| Activity | Verb + object, sentence case, unique within the pipeline, at most 55 characters | `Copy landing to bronze` |
| SQL schema for control objects | `ctl` | `ctl.run_log` |
| Stored procedure | `usp_<verb>_<object>` | `ctl.usp_log_run_end` |
| View | `v_<name>` | `ctl.v_run_status` |

General rules:

- Use lowercase snake_case for items, tables, columns created by us, parameters and SQL objects. Keep SAP field names as delivered, in uppercase.
- Add a description to every item and every pipeline activity.
- Lineage columns added by pipelines start with an underscore and are uppercase: `_LOAD_DATE`, `_SOURCE_FILE`, `_PIPELINE_RUN_ID`.
