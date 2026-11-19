# Demo runbook (30 minutes)

**Goal.** Show that an agent can build Fabric Data Factory pipelines that open and run correctly. Two things make that work: real workspace state, read through a read-only MCP server, and controlled writes to a DEV workspace.

**Roles.** The session works best with two presenters:
- **Presenter A:** the Fabric context and the Fabric UI.
- **Presenter B:** drives VS Code and Copilot.

## Pre-flight (T-60 to T-15 minutes)

1. **Resume the capacity** if it is paused, for example by the auto-pause Logic App in `infra/`. A capacity admin can do this in the Azure portal, or with:
   ```bash
   az rest --method post --url "https://management.azure.com$(jq -r .capacity.armId environment/fabric-environment.json)/resume?api-version=2023-11-01"
   ```
2. **Get to the clean baseline:** no pipelines, no bronze tables, empty run log.
   ```bash
   python scripts/fabric_env.py reset --yes
   python scripts/fabric_env.py status
   ```
3. **Sign in to your tenant:** `az login --tenant <tenant-id>`.
4. **Start the servers.** In a **Copilot** harness session, run **Chat: Open Customizations** and select **MCP Servers**. Confirm that `fabricReadOnly` (42 tools) and `fabricDevWrite` (6 tools) are running. Disable any other Fabric MCP servers configured in the user profile. Use a normal agent session, not Autopilot, because Autopilot cancels the run approval.
5. **Prepare the Fabric UI.** Open the workspace in a browser tab and sign in with the same identity.
6. **Run a smoke test:** `/demo-1-read-state`. It should list `lh_bronze`, `wh_control`, 10 landing tables and no pipelines.

## Agenda

| Time | Who | What |
|---|---|---|
| 0–3 | A | **Scenario.** A metadata-driven SAP ingestion framework with landing, a control warehouse and master/child pipelines. **The question:** can an agent build pipelines that open in Fabric and have the right connections? |
| 3–8 | B | **Repo tour.** `copilot-instructions.md` gives the agent context instead of starting from scratch. `docs/` holds standards and design. `.mcp.json` has two servers: read-only, and write with a six-tool allow-list. Also show the skills |
| 8–12 | B | **`/demo-1-read-state`.** The agent reads the real state. Point out that it gets real IDs and endpoints instead of guessing them. Optionally, ask the read-only server to create something and show that it can't |
| 12–22 | B + A | **`/demo-2-build-pipelines`.** Plan, JSON written to `fabric/`, deploy from the repo folder, run (approve the prompt), verify. Presenter A opens the pipeline in Fabric and shows the activities, connections and run monitor |
| 22–26 | B | **`/demo-3-incremental-load`.** Runs the master from demo 2 for the next date: FULL tables are overwritten, INCREMENTAL tables appended, reruns are safe |
| 26–30 | Both | **Governance.** Read-only by default, writes only in DEV under RBAC, approval for every run, Git as the source of truth, small capacity footprint. Then Q&A |

Stretch, if time allows: `/demo-4-catchup`.

## Talking points

- **Why pipeline generation often fails.** The agent doesn't know the workspace (item IDs, SQL endpoints) or the exact definition format, so it invents connection blocks. The read-only server and a validated patterns file fix most of that without granting any write access.
- **Two levels of trust.**
  - *Read-only.* The agent reads state and writes JSON to the repo. A human deploys it through Git.
  - *Controlled write in DEV.* The agent also deploys and test-runs. Both use the same repo and instructions.
- **The guardrails are layered.**
  - Server flags: `--read-only` and `--tool`.
  - Fabric RBAC: Contributor on DEV only.
  - Approval prompts in VS Code.
  - Git review before promotion to test and prod.
- **Fabric Warehouse detail.** Parallel UPDATEs on the same table conflict. Control tables are append-only, with views for current state.

## Fallbacks

- **The generated pipeline fails or takes too long.** Deploy the validated reference implementation and run it (about 3 minutes):
  ```bash
  python scripts/fabric_env.py deploy-reference
  ```
  It reads the definitions from the `fallback` branch, so your working tree stays as it is. The definitions use `{{...}}` tokens that `deploy` resolves from `environment/fabric-environment.json`; to show them, open `fabric/` on the `fallback` branch. The same command shows the finished result before a rehearsal; `reset --yes` removes it again.
- **A run is cancelled before it starts.** Fabric shows no job and `ctl.v_run_status` stays empty. The approval prompt was declined or cancelled, usually because the session is in Autopilot. Switch to a normal agent session and run it again, or run it from the terminal with `python scripts/fabric_env.py run pl_bronze_sap_master -p p_load_date=<date>`.
- **The MCP server won't authenticate.** Check `az account show` (it must show your tenant). Restart the servers after `az login`.
- **A presenter has no workspace access.** Grant Contributor with `python scripts/fabric_env.py grant`, or let the other presenter drive.
- **The SQL helper is unavailable** (no go-sqlcmd). Query `wh_control` in the Fabric UI or with the MSSQL extension.

## After the session

Remove any access you granted for the session, then clean up and pause the capacity:

```bash
python scripts/fabric_env.py reset --yes
az rest --method post --url "https://management.azure.com$(jq -r .capacity.armId environment/fabric-environment.json)/suspend?api-version=2023-11-01"
```
