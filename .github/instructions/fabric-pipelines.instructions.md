---
applyTo: "fabric/**"
description: Rules and validated JSON patterns for Fabric Data Factory pipeline definitions
---
# Fabric pipeline definitions

Every snippet below was validated on 17 November 2026: created through the Fabric REST API, then run end to end. Use them as they are; most broken generated pipelines fail on the connection blocks. Replace `<workspace.id>`, `<lakehouse.id>`, `<warehouse.id>` and `<warehouse.connectionString>` with the values from `environment/fabric-environment.json`. Never leave placeholders in a deployed definition.

## Files

Each pipeline lives in `fabric/<pipeline-name>.DataPipeline/` and has two files:

- `pipeline-content.json`: `{"properties": {"description": "...", "activities": [...], "parameters": {...}, "variables": {...}, "annotations": []}}`
- `.platform`:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  "metadata": { "type": "DataPipeline", "displayName": "<pipeline-name>", "description": "<one line>" },
  "config": { "version": "2.0", "logicalId": "<new GUID>" }
}
```

## Rules

- **No connection objects.** The lakehouse and warehouse are in the same workspace, so reference them inline with the `linkedService` blocks below. Do not invent `externalReferences` or connection IDs.
- **Expressions** are written as `{"value": "@...", "type": "Expression"}`.
- **Names.**
  - Parameters start with `p_` and variables with `v_`.
  - Activity names are short phrases such as "Copy landing to bronze". They are referenced in expressions, so never rename one without updating every reference.
- **Required properties.**
  - Every activity has a `description`.
  - Lookup, Copy and stored-procedure activities have a `policy` with `retry`.
- **Child pipelines.** Call them with `ExecutePipeline`; `referenceName` is the child pipeline's **item ID**, so create the child first. ForEach cannot contain another ForEach, so call a child pipeline instead. Keep to two levels.
- **Dates.** Pass stored-procedure date parameters as `String` (`YYYY-MM-DD`); SQL converts them.
- **Warehouse writes** from parallel activities must be INSERTs, as the `ctl` procedures are. Fabric Warehouse aborts concurrent UPDATEs on the same table.
- **Overwrite vs append.** `tableActionOption` takes `Overwrite` or `Append` and accepts an expression.
- **Querying bronze.** Use `scripts/fabric_env.py sql --target lakehouse`, which refreshes the SQL endpoint metadata first.

## Lakehouse linked service

For sources use `rootFolder` `Files`; for sink tables use `Tables`.

```json
"linkedService": {
  "name": "lh_bronze",
  "properties": {
    "annotations": [],
    "type": "Lakehouse",
    "typeProperties": { "workspaceId": "<workspace.id>", "artifactId": "<lakehouse.id>", "rootFolder": "Files" }
  }
}
```

## Warehouse linked service

In `SqlServerStoredProcedure` activities this block sits at activity level, next to `typeProperties`. In `Lookup` and `Copy` it sits inside `datasetSettings`.

```json
"linkedService": {
  "name": "wh_control",
  "objectId": "<warehouse.id>",
  "properties": {
    "annotations": [],
    "type": "DataWarehouse",
    "typeProperties": {
      "endpoint": "<warehouse.connectionString>",
      "artifactId": "<warehouse.id>",
      "workspaceId": "<workspace.id>"
    }
  }
}
```

## Stored procedure activity

```json
{
  "name": "Log run start",
  "description": "Insert a Started event into ctl.run_log.",
  "type": "SqlServerStoredProcedure",
  "dependsOn": [],
  "policy": { "timeout": "0.00:10:00", "retry": 2, "retryIntervalInSeconds": 30, "secureOutput": false, "secureInput": false },
  "typeProperties": {
    "storedProcedureName": "[ctl].[usp_log_run_start]",
    "storedProcedureParameters": {
      "pipeline_run_id": { "value": { "value": "@pipeline().RunId", "type": "Expression" }, "type": "String" },
      "pipeline_name": { "value": "pl_bronze_sap_child", "type": "String" },
      "rows_copied": { "value": { "value": "@activity('Copy landing to bronze').output.rowsCopied", "type": "Expression" }, "type": "Int64" }
    }
  },
  "linkedService": { "...": "warehouse linked service (activity level)" }
}
```

## Lookup that calls a stored procedure

```json
{
  "name": "Get objects to load",
  "type": "Lookup",
  "typeProperties": {
    "source": {
      "type": "DataWarehouseSource",
      "sqlReaderStoredProcedureName": "[ctl].[usp_get_objects_to_load]",
      "storedProcedureParameters": {
        "load_group": { "type": "String", "value": { "value": "@pipeline().parameters.p_load_group", "type": "Expression" } },
        "load_date": { "type": "String", "value": { "value": "@variables('v_load_date')", "type": "Expression" } }
      },
      "queryTimeout": "02:00:00",
      "partitionOption": "None"
    },
    "firstRowOnly": false,
    "datasetSettings": {
      "annotations": [],
      "linkedService": { "...": "warehouse linked service" },
      "type": "DataWarehouseTable",
      "schema": [],
      "typeProperties": {}
    }
  }
}
```

The rows are available as `@activity('Get objects to load').output.value`.

## Copy landing CSV to a bronze table

```json
"typeProperties": {
  "source": {
    "type": "DelimitedTextSource",
    "additionalColumns": [
      { "name": "_LOAD_DATE", "value": { "value": "@pipeline().parameters.p_load_date", "type": "Expression" } },
      { "name": "_SOURCE_FILE", "value": "$$FILEPATH" },
      { "name": "_PIPELINE_RUN_ID", "value": { "value": "@pipeline().RunId", "type": "Expression" } }
    ],
    "storeSettings": { "type": "LakehouseReadSettings", "recursive": true, "wildcardFileName": "*.csv", "enablePartitionDiscovery": false },
    "formatSettings": { "type": "DelimitedTextReadSettings" },
    "datasetSettings": {
      "annotations": [],
      "linkedService": { "...": "lakehouse linked service, rootFolder Files" },
      "type": "DelimitedText",
      "typeProperties": {
        "location": { "type": "LakehouseLocation", "folderPath": { "value": "@pipeline().parameters.p_landing_path", "type": "Expression" } },
        "columnDelimiter": ",", "escapeChar": "\\", "firstRowAsHeader": true, "quoteChar": "\""
      },
      "schema": []
    }
  },
  "sink": {
    "type": "LakehouseTableSink",
    "tableActionOption": { "value": "@pipeline().parameters.p_table_action", "type": "Expression" },
    "partitionOption": "None",
    "datasetSettings": {
      "annotations": [],
      "linkedService": { "...": "lakehouse linked service, rootFolder Tables" },
      "type": "LakehouseTable",
      "schema": [],
      "typeProperties": { "table": { "value": "@pipeline().parameters.p_target_table", "type": "Expression" } }
    }
  },
  "enableStaging": false,
  "translator": { "type": "TabularTranslator", "typeConversion": true, "typeConversionSettings": { "allowDataTruncation": true, "treatBooleanAsNumber": false } }
}
```

`folderPath` is relative to `Files`, for example `landing/sap_s4/MARA/load_date=2026-11-12`. Outputs are `.output.rowsCopied` and, on the failure path, `.error.message`.

## ForEach with ExecutePipeline

```json
{
  "name": "For each object",
  "type": "ForEach",
  "dependsOn": [ { "activity": "Get objects to load", "dependencyConditions": [ "Succeeded" ] } ],
  "typeProperties": {
    "items": { "value": "@activity('Get objects to load').output.value", "type": "Expression" },
    "isSequential": false,
    "batchCount": 4,
    "activities": [
      {
        "name": "Load object to bronze",
        "type": "ExecutePipeline",
        "dependsOn": [],
        "policy": { "secureInput": false },
        "typeProperties": {
          "pipeline": { "referenceName": "<child pipeline item id>", "type": "PipelineReference" },
          "waitOnCompletion": true,
          "parameters": {
            "p_source_object": { "value": "@item().source_object", "type": "Expression" },
            "p_parent_run_id": { "value": "@pipeline().RunId", "type": "Expression" }
          }
        }
      }
    ]
  }
}
```

## Failure handling

Log the failure, then fail the run so the parent sees it.

```json
{
  "name": "Fail pipeline",
  "type": "Fail",
  "dependsOn": [ { "activity": "Log run end - failed", "dependencyConditions": [ "Succeeded" ] } ],
  "typeProperties": {
    "message": { "value": "@concat('Bronze load failed for ', pipeline().parameters.p_source_object, ': ', activity('Copy landing to bronze').error.message)", "type": "Expression" },
    "errorCode": "BRONZE_LOAD_FAILED"
  }
}
```

## Set variable and parameters

```json
{ "name": "Set load date", "type": "SetVariable", "dependsOn": [], "policy": { "secureOutput": false, "secureInput": false },
  "typeProperties": { "variableName": "v_load_date",
    "value": { "value": "@if(empty(pipeline().parameters.p_load_date), formatDateTime(addDays(utcNow(), -1), 'yyyy-MM-dd'), pipeline().parameters.p_load_date)", "type": "Expression" } } }
```

```json
"parameters": { "p_load_group": { "type": "string", "defaultValue": "ALL" }, "p_load_date": { "type": "string", "defaultValue": "" } },
"variables": { "v_load_date": { "type": "String" } }
```
