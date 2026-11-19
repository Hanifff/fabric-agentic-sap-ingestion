#!/usr/bin/env python3
"""Provision, inspect and reset the Fabric demo environment.

Requires Python 3.9+, the Azure CLI signed in to your tenant (`az login --tenant <tenant-id>`),
and go-sqlcmd (https://github.com/microsoft/go-sqlcmd) for the control warehouse.

  python scripts/fabric_env.py provision --capacity <name-or-id>  # workspace, lh_bronze, wh_control -> environment/fabric-environment.json
  python scripts/fabric_env.py upload-data        # data/sap_s4 -> lh_bronze Files/landing/sap_s4
  python scripts/fabric_env.py control-db         # ctl schema, procedures, config seed in wh_control
  python scripts/fabric_env.py status             # capacity state, items, role assignments
  python scripts/fabric_env.py sql "SELECT ..."   # T-SQL against wh_control (or --target lakehouse)
  python scripts/fabric_env.py deploy fabric/pl_x.DataPipeline
  python scripts/fabric_env.py run pl_x -p p_load_date=2026-11-12
  python scripts/fabric_env.py deploy-reference   # validated pipelines from the fallback branch, then one run
  python scripts/fabric_env.py reset --yes        # back to the clean demo baseline
  python scripts/fabric_env.py grant --principal-id <entra-object-id> --role Contributor
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "environment" / "fabric-environment.json"
CONFIG_CSV = ROOT / "metadata" / "ingestion_config.csv"
DATA_DIR = ROOT / "data" / "sap_s4"
SQL_DIR = ROOT / "sql" / "wh_control"
API = "https://api.fabric.microsoft.com/v1"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
FABRIC_SCOPE = "https://api.fabric.microsoft.com"
STORAGE_SCOPE = "https://storage.azure.com"
LANDING_ROOT = "Files/landing/sap_s4"

DEFAULTS = {
    "workspaceName": "Agentic SAP Demo - DEV",
    "lakehouseName": "lh_bronze",
    "warehouseName": "wh_control",
}
# Item types created during demos/rehearsals; reset removes these, never the lakehouse/warehouse.
REMOVABLE_TYPES = {"DataPipeline", "Notebook", "CopyJob", "Dataflow", "VariableLibrary", "SparkJobDefinition",
                   "Environment", "Report"}


# ----------------------------------------------------------------------------- environment file
def load_env(required: bool = True) -> dict:
    if ENV_FILE.exists():
        return json.loads(ENV_FILE.read_text())
    if required:
        sys.exit(f"{ENV_FILE.relative_to(ROOT)} not found - run 'provision' first")
    return {}


def save_env(env: dict) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(json.dumps(env, indent=2) + "\n")


_TENANT: str | None = None  # set by 'provision --tenant'


def tenant_id() -> str | None:
    """Tenant for tokens: 'provision --tenant', else the environment file, else None (the Azure CLI's current tenant)."""
    return _TENANT or load_env(required=False).get("tenantId")


def az(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("az") or "az"  # on Windows az is az.cmd, which subprocess only starts by its full path
    return subprocess.run([exe, *args], capture_output=True, text=True)


# ----------------------------------------------------------------------------- HTTP
_TOKENS: dict[str, str] = {}


def token(resource: str) -> str:
    if resource not in _TOKENS:
        tenant = tenant_id()
        out = az("account", "get-access-token", "--resource", resource, *(["--tenant", tenant] if tenant else []),
                 "--query", "accessToken", "-o", "tsv")
        if out.returncode != 0:
            sys.exit(f"Could not get a token for {resource}. Run 'az login' first.\n{out.stderr.strip()}")
        _TOKENS[resource] = out.stdout.strip()
    return _TOKENS[resource]


def http(method: str, url: str, *, json_body=None, data: bytes | None = None, resource: str = FABRIC_SCOPE,
         headers: dict | None = None, retries: int = 6):
    hdrs = {"Authorization": f"Bearer {token(resource)}", **(headers or {})}
    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            payload = err.read()
            if err.code == 429 or err.code >= 500:
                time.sleep(min(int(err.headers.get("Retry-After") or 5 * (attempt + 1)), 60))
                continue
            return err.code, err.headers, payload
    raise RuntimeError(f"{method} {url} kept failing after {retries} attempts")


def as_json(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")


def fabric(method: str, path: str, body=None, ok=(200, 201, 202)):
    url = path if path.startswith("http") else API + path
    status, headers, raw = http(method, url, json_body=body)
    if status not in ok:
        raise RuntimeError(f"{method} {path} -> HTTP {status}: {as_json(raw)}")
    if status == 202 and headers.get("Location") and "/operations/" in headers.get("Location", ""):
        return wait_operation(headers["Location"], int(headers.get("Retry-After") or 3))
    return as_json(raw)


def wait_operation(location: str, delay: int):
    while True:
        time.sleep(delay)
        _, headers, raw = http("GET", location)
        op = as_json(raw) or {}
        if op.get("status") == "Succeeded":
            status, _, result = http("GET", location.rstrip("/") + "/result")
            return as_json(result) if status == 200 else op
        if op.get("status") in ("Failed", "Cancelled"):
            raise RuntimeError(f"Long-running operation failed: {op}")
        delay = int(headers.get("Retry-After") or delay)


def list_all(path: str) -> list:
    items, url = [], API + path
    while url:
        page = fabric("GET", url)
        items += page.get("value", [])
        url = page.get("continuationUri")
    return items


def find_item(ws_id: str, name: str, item_type: str | None = None) -> dict | None:
    for item in list_all(f"/workspaces/{ws_id}/items"):
        if item["displayName"] == name and (item_type is None or item["type"] == item_type):
            return item
    return None


# ----------------------------------------------------------------------------- provision
def ensure_item(ws_id: str, collection: str, name: str, description: str) -> dict:
    existing = next((i for i in list_all(f"/workspaces/{ws_id}/{collection}") if i["displayName"] == name), None)
    if existing:
        print(f"  {collection[:-1]} '{name}' exists")
        item_id = existing["id"]
    else:
        created = fabric("POST", f"/workspaces/{ws_id}/{collection}", {"displayName": name, "description": description})
        item_id = created["id"] if created and "id" in created else \
            next(i for i in list_all(f"/workspaces/{ws_id}/{collection}") if i["displayName"] == name)["id"]
        print(f"  {collection[:-1]} '{name}' created")
    return fabric("GET", f"/workspaces/{ws_id}/{collection}/{item_id}")


def capacity_arm_id(name: str) -> str | None:
    """ARM ID of the capacity, for resume and suspend, from Azure Resource Graph; None if the CLI can't see it."""
    query = {"query": "resources | where type =~ 'microsoft.fabric/capacities' and name =~ '"
                      + name.replace("'", "") + "' | project id"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:  # a file avoids quoting on Windows
        json.dump(query, tmp)
    try:
        out = az("rest", "--method", "post", "--url", "https://management.azure.com/providers/"
                 "Microsoft.ResourceGraph/resources?api-version=2022-10-01", "--body", f"@{tmp.name}",
                 "--query", "data[0].id", "-o", "tsv")
    finally:
        pathlib.Path(tmp.name).unlink(missing_ok=True)
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def provision(args) -> None:
    global _TENANT
    env = load_env(required=False)
    _TENANT = args.tenant or env.get("tenantId")
    if not _TENANT:
        out = az("account", "show", "--query", "tenantId", "-o", "tsv")
        if out.returncode != 0:
            sys.exit(f"Run 'az login --tenant <tenant-id>' first.\n{out.stderr.strip()}")
        _TENANT = out.stdout.strip()
    wanted = args.capacity or env.get("capacity", {}).get("id")
    if not wanted:
        sys.exit("Pass --capacity with the name or ID of a Fabric capacity you are admin or contributor on.")
    capacities = list_all("/capacities")
    capacity = next((c for c in capacities if wanted.lower() in (c["id"].lower(), c["displayName"].lower())), None)
    if not capacity:
        sys.exit(f"Capacity '{wanted}' not found. Capacities you can use: "
                 + (", ".join(c["displayName"] for c in capacities) or "none"))
    if capacity.get("state") != "Active":
        sys.exit(f"Capacity '{capacity['displayName']}' is {capacity.get('state')}. Resume it, then run provision again.")
    capacity_id = capacity["id"]
    ws_name = args.workspace_name or env.get("workspace", {}).get("name", DEFAULTS["workspaceName"])
    ws = next((w for w in list_all("/workspaces") if w["displayName"] == ws_name), None)
    if not ws:
        ws = fabric("POST", "/workspaces", {
            "displayName": ws_name, "capacityId": capacity_id,
            "description": "Demo: AI-assisted Fabric development with GitHub Copilot + Fabric MCP. Synthetic SAP "
                           "S/4HANA-like data (fictional company). Dev workspace: agents may create/modify items here."})
        print(f"  workspace '{ws_name}' created")
    elif ws.get("capacityId") != capacity_id:
        fabric("POST", f"/workspaces/{ws['id']}/assignToCapacity", {"capacityId": capacity_id})
        print(f"  workspace '{ws_name}' assigned to capacity")
    else:
        print(f"  workspace '{ws_name}' exists")
    ws_id = ws["id"]

    lh = ensure_item(ws_id, "lakehouses", DEFAULTS["lakehouseName"],
                     "Bronze layer: SAP landing files under Files/landing and bronze Delta tables under Tables.")
    wh = ensure_item(ws_id, "warehouses", DEFAULTS["warehouseName"],
                     "Control layer: ingestion config, watermarks, run log and stored procedures (schema ctl).")
    for _ in range(30):  # the lakehouse SQL analytics endpoint is provisioned asynchronously
        sql_ep = (lh.get("properties") or {}).get("sqlEndpointProperties") or {}
        if sql_ep.get("connectionString"):
            break
        time.sleep(10)
        lh = fabric("GET", f"/workspaces/{ws_id}/lakehouses/{lh['id']}")
    previous = env.get("capacity", {})
    arm_id = (previous.get("armId") if previous.get("id") == capacity_id else None) \
        or capacity_arm_id(capacity["displayName"])
    if not arm_id:
        print("  capacity ARM ID not found in your Azure subscriptions; set capacity.armId by hand to use "
              "the resume and suspend commands in docs/demo-runbook.md")
    lh_props, wh_props = lh.get("properties") or {}, wh.get("properties") or {}
    env = {
        "tenantId": _TENANT,
        "capacity": {"id": capacity_id, "name": capacity.get("displayName"), "sku": capacity.get("sku"),
                     "region": capacity.get("region"), "armId": arm_id},
        "workspace": {"id": ws_id, "name": ws_name,
                      "url": f"https://app.fabric.microsoft.com/groups/{ws_id}?experience=fabric-developer"
                             f"&ctid={_TENANT}"},
        "lakehouse": {"id": lh["id"], "name": lh["displayName"],
                      "oneLakeFilesPath": lh_props.get("oneLakeFilesPath"),
                      "oneLakeTablesPath": lh_props.get("oneLakeTablesPath"),
                      "sqlEndpointId": (lh_props.get("sqlEndpointProperties") or {}).get("id"),
                      "sqlEndpointConnectionString": (lh_props.get("sqlEndpointProperties") or {}).get("connectionString")},
        "warehouse": {"id": wh["id"], "name": wh["displayName"],
                      "connectionString": wh_props.get("connectionString") or wh_props.get("connectionInfo")},
        "landingRoot": LANDING_ROOT,
    }
    save_env(env)
    print(f"Wrote {ENV_FILE.relative_to(ROOT)}")


# ----------------------------------------------------------------------------- OneLake upload
def upload_data(_args) -> None:
    env = load_env()
    ws_id, lh_id = env["workspace"]["id"], env["lakehouse"]["id"]
    files = sorted(DATA_DIR.rglob("*.csv"))
    if not files:
        sys.exit("No files under data/sap_s4 - run scripts/generate_sap_sample_data.py first")
    common = {"x-ms-version": "2023-11-03"}
    token(STORAGE_SCOPE)  # acquire once before the worker threads start

    def upload(f: pathlib.Path) -> None:
        rel = f.relative_to(DATA_DIR).as_posix()
        url = f"{ONELAKE}/{ws_id}/{lh_id}/{LANDING_ROOT}/{urllib.parse.quote(rel)}"
        data = f.read_bytes()
        steps = [("PUT", f"{url}?resource=file", b"", {}, (201,)),
                 ("PATCH", f"{url}?action=append&position=0", data, {"Content-Type": "application/octet-stream"}, (202,)),
                 ("PATCH", f"{url}?action=flush&position={len(data)}", b"", {}, (200,))]
        for method, step_url, body, extra, ok in steps:
            if method == "PATCH" and "append" in step_url and not data:
                continue
            status, _, raw = http(method, step_url, data=body, resource=STORAGE_SCOPE, headers={**common, **extra})
            if status not in ok:
                raise RuntimeError(f"{method} {rel} -> HTTP {status}: {as_json(raw)}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(upload, files))
    print(f"Uploaded {len(files)} files to {env['lakehouse']['name']}/{LANDING_ROOT}")


# ----------------------------------------------------------------------------- SQL
def sqlcmd_path() -> str:
    found = shutil.which("sqlcmd") or str(pathlib.Path.home() / ".local" / "bin" / "sqlcmd")
    if not pathlib.Path(found).exists():
        sys.exit("go-sqlcmd not found: https://github.com/microsoft/go-sqlcmd/releases")
    return found


def sql_target(env: dict, target: str) -> tuple[str, str]:
    if target == "lakehouse":
        return env["lakehouse"]["sqlEndpointConnectionString"], env["lakehouse"]["name"]
    return env["warehouse"]["connectionString"], env["warehouse"]["name"]


def run_sql(server: str, database: str, *, query: str | None = None, file: pathlib.Path | None = None,
            echo: bool = True) -> str:
    cmd = [sqlcmd_path(), "-S", server, "-d", database, "--authentication-method", "ActiveDirectoryDefault",
           "-b", "-W", "-s", "|"]
    cmd += ["-Q", query] if query else ["-i", str(file)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Fabric appends a "Statement ID | Query hash | Distributed request ID" line to every result set.
    output = "\n".join(line for line in result.stdout.splitlines() if not line.startswith("Statement ID:"))
    if result.returncode != 0:
        raise RuntimeError(f"sqlcmd failed ({file or query[:60]}):\n{output}\n{result.stderr}")
    if echo and output.strip():
        print(output.strip())
    return output


def refresh_sql_endpoint(env: dict) -> None:
    """Sync the lakehouse SQL analytics endpoint with the latest Delta table versions."""
    ws_id, endpoint_id = env["workspace"]["id"], env["lakehouse"]["sqlEndpointId"]
    result = fabric("POST", f"/workspaces/{ws_id}/sqlEndpoints/{endpoint_id}/refreshMetadata", {})
    failed = [t["tableName"] for t in (result or {}).get("value", []) if t.get("status") == "Failure"]
    if failed:
        print(f"  SQL endpoint refresh failed for: {', '.join(failed)}", file=sys.stderr)


def seed_sql() -> str:
    def q(value: str) -> str:
        return "NULL" if value in ("", None) else "'" + value.replace("'", "''") + "'"

    rows = list(csv.DictReader(CONFIG_CSV.open(encoding="utf-8")))
    values = ",\n".join(
        f"({q(r['source_system'])}, {q(r['source_object'])}, {q(r['object_description'])}, {q(r['load_group'])}, "
        f"{q(r['load_type'])}, {q(r['business_key'])}, {q(r['watermark_column'])}, {q(r['landing_folder'])}, "
        f"{q(r['target_table'])}, {int(r['priority'])}, {int(r['is_active'])})" for r in rows)
    return ("TRUNCATE TABLE ctl.ingestion_config;\n"
            "INSERT INTO ctl.ingestion_config (source_system, source_object, object_description, load_group, load_type,"
            " business_key, watermark_column, landing_folder, target_table, priority, is_active)\nVALUES\n"
            f"{values};\nTRUNCATE TABLE ctl.watermark;\nTRUNCATE TABLE ctl.run_log;\n")


def seed_control(env: dict) -> None:
    server, db = sql_target(env, "warehouse")
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as tmp:
        tmp.write(seed_sql())
    try:
        run_sql(server, db, file=pathlib.Path(tmp.name), echo=False)
    finally:
        pathlib.Path(tmp.name).unlink(missing_ok=True)
    print(f"  seeded ctl.ingestion_config from {CONFIG_CSV.relative_to(ROOT)}; watermark and run_log emptied")


def control_db(_args) -> None:
    env = load_env()
    server, db = sql_target(env, "warehouse")
    for script in sorted(SQL_DIR.glob("*.sql")):
        run_sql(server, db, file=script, echo=False)
        print(f"  ran {script.relative_to(ROOT)}")
    seed_control(env)


def sql_cmd(args) -> None:
    env = load_env()
    if args.target == "lakehouse" and not args.no_refresh:
        refresh_sql_endpoint(env)  # otherwise the endpoint can serve stale Delta metadata after a load
    server, db = sql_target(env, args.target)
    run_sql(server, db, query=args.query)


# ----------------------------------------------------------------------------- deploy / run pipelines
TOKEN_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def resolve_tokens(text: str, env: dict) -> str:
    """Replace {{workspace.id}}, {{lakehouse.id}}, {{warehouse.connectionString}}, {{item:<name>}} ..."""
    def repl(match):
        key = match.group(1)
        if key.startswith("item:"):
            item = find_item(env["workspace"]["id"], key[5:])
            if not item:
                raise RuntimeError(f"Token {{{{{key}}}}}: item '{key[5:]}' not found - deploy it first")
            return item["id"]
        section, _, field = key.partition(".")
        return str(env[section][field])
    return TOKEN_RE.sub(repl, text)


def deploy(args) -> None:
    env = load_env()
    ws_id = env["workspace"]["id"]
    folder = pathlib.Path(args.path)
    meta = {}
    if (folder / ".platform").exists():
        meta = json.loads((folder / ".platform").read_text()).get("metadata", {})
    name = meta.get("displayName") or folder.name.rsplit(".", 1)[0]
    item_type = meta.get("type") or folder.name.rsplit(".", 1)[-1]
    content = resolve_tokens((folder / "pipeline-content.json").read_text(), env)
    json.loads(content)  # fail fast on invalid JSON
    parts = [{"path": "pipeline-content.json", "payloadType": "InlineBase64",
              "payload": base64.b64encode(content.encode()).decode()}]
    existing = find_item(ws_id, name, item_type)
    if existing:
        fabric("POST", f"/workspaces/{ws_id}/items/{existing['id']}/updateDefinition", {"definition": {"parts": parts}})
        print(f"Updated {item_type} '{name}' ({existing['id']})")
    else:
        created = fabric("POST", f"/workspaces/{ws_id}/items", {
            "displayName": name, "type": item_type, "description": meta.get("description", ""),
            "definition": {"parts": parts}})
        print(f"Created {item_type} '{name}' ({(created or {}).get('id')})")


def run_pipeline(args) -> None:
    env = load_env()
    ws_id = env["workspace"]["id"]
    item = find_item(ws_id, args.name, "DataPipeline")
    if not item:
        sys.exit(f"Pipeline '{args.name}' not found")
    params = dict(p.split("=", 1) for p in args.param or [])
    body = {"executionData": {"parameters": params}} if params else {}
    status, headers, raw = http("POST", f"{API}/workspaces/{ws_id}/items/{item['id']}/jobs/instances?jobType=Pipeline",
                                json_body=body)
    if status != 202:
        sys.exit(f"Run request failed: HTTP {status}: {as_json(raw)}")
    location = headers["Location"]
    print(f"Started {args.name} {params or ''}")
    while True:
        time.sleep(10)
        _, _, raw = http("GET", location)
        job = as_json(raw) or {}
        print(f"  {time.strftime('%H:%M:%S')} {job.get('status')}")
        if job.get("status") in ("Completed", "Failed", "Cancelled", "Deduped"):
            break
    if job.get("failureReason"):
        print(json.dumps(job["failureReason"], indent=2))
    sys.exit(0 if job.get("status") == "Completed" else 1)


REFERENCE_REF = "origin/fallback"
REFERENCE_PIPELINES = ["pl_bronze_sap_child", "pl_bronze_sap_master"]  # child first: the master references its ID


def deploy_reference(args) -> None:
    """Deploy the validated pipelines from the fallback branch, then run the master once.

    Reads the definitions straight from Git, so fabric/ and the rest of the working tree stay untouched.
    """
    print(f"Deploying the reference pipelines from {args.ref}")
    with tempfile.TemporaryDirectory() as tmp:
        for name in REFERENCE_PIPELINES:
            folder = pathlib.Path(tmp) / f"{name}.DataPipeline"
            folder.mkdir()
            for part in (".platform", "pipeline-content.json"):
                shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{args.ref}:fabric/{folder.name}/{part}"],
                                       capture_output=True)
                if shown.returncode != 0:
                    sys.exit(f"Cannot read fabric/{folder.name}/{part} from {args.ref}: "
                             f"{shown.stderr.decode().strip()}\nRun 'git fetch origin' and try again.")
                (folder / part).write_bytes(shown.stdout)
            deploy(argparse.Namespace(path=str(folder)))
    if not args.no_run:
        run_pipeline(argparse.Namespace(name=REFERENCE_PIPELINES[-1], param=[f"p_load_date={args.load_date}"]))


# ----------------------------------------------------------------------------- reset / status / grant
def list_tables_dirs(env: dict) -> list[str]:
    ws_id, lh_id = env["workspace"]["id"], env["lakehouse"]["id"]
    status, _, raw = http("GET", f"{ONELAKE}/{ws_id}?resource=filesystem&recursive=false&directory={lh_id}/Tables",
                          resource=STORAGE_SCOPE, headers={"x-ms-version": "2023-11-03"})
    if status != 200:
        raise RuntimeError(f"List Tables failed: HTTP {status}: {as_json(raw)}")
    return [p["name"] for p in (as_json(raw) or {}).get("paths", []) if str(p.get("isDirectory")).lower() == "true"]


def reset(args) -> None:
    sqlcmd_path()  # reseeding ctl needs go-sqlcmd: stop now rather than after the deletes
    env = load_env()
    ws_id = env["workspace"]["id"]
    keep = {env["lakehouse"]["id"], env["warehouse"]["id"]}
    items = [i for i in list_all(f"/workspaces/{ws_id}/items") if i["id"] not in keep and i["type"] in REMOVABLE_TYPES]
    tables = list_tables_dirs(env)
    print("Will delete items:", ", ".join(f"{i['displayName']} ({i['type']})" for i in items) or "none")
    print("Will delete bronze tables:", ", ".join(t.rsplit("/", 1)[-1] for t in tables) or "none")
    print("Will reseed wh_control ctl tables; landing files are kept.")
    if not args.yes:
        sys.exit("Dry run. Re-run with --yes to apply.")
    for item in sorted(items, key=lambda i: i["displayName"], reverse=True):  # masters before children
        fabric("DELETE", f"/workspaces/{ws_id}/items/{item['id']}")
    for table in tables:
        status, _, raw = http("DELETE", f"{ONELAKE}/{ws_id}/{table}?recursive=true", resource=STORAGE_SCOPE,
                              headers={"x-ms-version": "2023-11-03"})
        if status not in (200, 202):
            raise RuntimeError(f"Delete {table} failed: HTTP {status}: {as_json(raw)}")
    seed_control(env)
    print("Reset complete.")


def status_cmd(_args) -> None:
    env = load_env()
    ws_id = env["workspace"]["id"]
    capacity = next((c for c in fabric("GET", "/capacities")["value"] if c["id"] == env["capacity"]["id"]), {})
    print(f"Workspace : {env['workspace']['name']} ({ws_id})\n  {env['workspace']['url']}")
    print(f"Capacity  : {capacity.get('displayName')} {capacity.get('sku')} - {capacity.get('state')}")
    print("Items     :")
    for item in sorted(list_all(f"/workspaces/{ws_id}/items"), key=lambda i: (i["type"], i["displayName"])):
        print(f"  {item['type']:<16} {item['displayName']:<32} {item['id']}")
    print("Access    :")
    for ra in list_all(f"/workspaces/{ws_id}/roleAssignments"):
        p = ra["principal"]
        detail = p.get("userDetails", {}).get("userPrincipalName") or p.get("displayName")
        print(f"  {ra['role']:<12} {p['type']:<16} {detail}")


def grant(args) -> None:
    ws_id = load_env()["workspace"]["id"]
    body = {"principal": {"id": args.principal_id, "type": args.type}, "role": args.role}
    status, _, raw = http("POST", f"{API}/workspaces/{ws_id}/roleAssignments", json_body=body)
    if status in (200, 201):
        print(f"Granted {args.role} to {args.principal_id}")
    elif status == 409 or "already" in str(as_json(raw)).lower():
        fabric("PATCH", f"/workspaces/{ws_id}/roleAssignments/{args.principal_id}", {"role": args.role})
        print(f"Updated role to {args.role} for {args.principal_id}")
    else:
        sys.exit(f"Grant failed: HTTP {status}: {as_json(raw)}")


# ----------------------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("provision", help="find or create the workspace, lh_bronze and wh_control; write the "
                                         "environment file")
    p.add_argument("--capacity", help="name or ID of a Fabric capacity you are admin or contributor on "
                                      "(required the first time)")
    p.add_argument("--workspace-name", help=f"default: '{DEFAULTS['workspaceName']}'")
    p.add_argument("--tenant", help="Entra tenant ID (default: the Azure CLI's current tenant)")
    p.set_defaults(func=provision)
    sub.add_parser("upload-data").set_defaults(func=upload_data)
    sub.add_parser("control-db").set_defaults(func=control_db)
    sub.add_parser("status").set_defaults(func=status_cmd)
    p = sub.add_parser("sql")
    p.add_argument("query")
    p.add_argument("--target", choices=["warehouse", "lakehouse"], default="warehouse")
    p.add_argument("--no-refresh", action="store_true", help="skip the lakehouse SQL endpoint metadata refresh")
    p.set_defaults(func=sql_cmd)
    p = sub.add_parser("deploy", help="create/update a DataPipeline from a Fabric Git-format folder")
    p.add_argument("path")
    p.set_defaults(func=deploy)
    p = sub.add_parser("run", help="run a pipeline and wait for it")
    p.add_argument("name")
    p.add_argument("-p", "--param", action="append", help="name=value (repeatable)")
    p.set_defaults(func=run_pipeline)
    p = sub.add_parser("deploy-reference", help="deploy the validated pipelines from the fallback branch, run once")
    p.add_argument("--ref", default=REFERENCE_REF, help="Git ref that holds fabric/ (default: %(default)s)")
    p.add_argument("--load-date", default="2026-11-12")
    p.add_argument("--no-run", action="store_true", help="deploy only")
    p.set_defaults(func=deploy_reference)
    p = sub.add_parser("reset")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=reset)
    p = sub.add_parser("grant")
    p.add_argument("--principal-id", required=True)
    p.add_argument("--role", default="Contributor", choices=["Admin", "Member", "Contributor", "Viewer"])
    p.add_argument("--type", default="User", choices=["User", "Group", "ServicePrincipal"])
    p.set_defaults(func=grant)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
