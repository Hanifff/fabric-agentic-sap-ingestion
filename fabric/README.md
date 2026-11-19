# fabric/

Fabric item definitions in Fabric Git format, one folder per item:

```
fabric/
  pl_bronze_sap_child.DataPipeline/
    pipeline-content.json
    .platform
```

- **Copilot writes here first**, following `.github/instructions/fabric-pipelines.instructions.md`.
- **Then deploys from the folder** to the DEV workspace with the `fabricDevWrite` MCP tools (`core_create-item` / `core_update-item-definition` with `definition-directory`), or with `python scripts/fabric_env.py deploy fabric/<name>.DataPipeline`.
- **Reset deletes only workspace items.** `python scripts/fabric_env.py reset --yes` removes the deployed pipelines and bronze tables but leaves these files alone; delete them yourself if you want a clean start.
