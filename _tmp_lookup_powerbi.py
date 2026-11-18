import os
from pathlib import Path

import requests

env: dict[str, str] = {}
raw = Path(os.environ["USERPROFILE"], ".cursor", "secrets", "mybelic.env").read_text(
    encoding="utf-8"
)
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip().strip('"').strip("'")

base = (env.get("MYBELIC_API_URL") or "https://license.malla.es").rstrip("/")
token = env.get("MYBELIC_API_TOKEN") or ""
cid = (
    env.get("MYBELIC_CUSTOMER_ID")
    or env.get("MYBELIC_PYTHON_DEPLOY_CUSTOMER_ID")
    or "4e27c722-48a2-4228-81c6-3317d20f98b1"
)
print("base", base)
print("token_len", len(token))
print("customer", cid)
headers = {"X-MyBeLic-Token": token}
response = requests.get(
    f"{base}/api/v1/admin/customers/{cid}", headers=headers, timeout=60
)
print("customer_status", response.status_code)
data = response.json()
cust = data.get("customer") if isinstance(data, dict) and "customer" in data else data
print("name", cust.get("name"))
print("saas", cust.get("bc_saas"))
print("company", cust.get("bc_default_company_name"))
print("env", cust.get("bc_environment") or cust.get("bc_default_environment"))
print("publish_time", cust.get("bc_default_publish_time"))
print("end_of_day", cust.get("bc_publish_end_of_day"))
keys = sorted(cust.keys()) if isinstance(cust, dict) else []
print("keys", ",".join(keys))
apps = cust.get("applications") or []
for app in apps:
    ext = app.get("extension") or {}
    name = str(ext.get("name") or app.get("name") or "")
    app_id = str(ext.get("id") or app.get("app_id") or "")
    if "power" in name.lower() or app_id == "d9cb442a-be20-49a4-a6d6-9ad6a9fbd205":
        print(
            "APP",
            app.get("record_id"),
            name,
            "ver",
            ext.get("version"),
            "installed",
            app.get("bc_installed_version"),
            "publisher",
            ext.get("publisher"),
        )

tasks = requests.get(
    f"{base}/api/v1/admin/customers/{cid}/tasks", headers=headers, timeout=60
)
print("tasks_status", tasks.status_code)
payload = tasks.json()
rows = payload
if isinstance(payload, dict):
    rows = payload.get("tasks") or payload.get("items") or []
pending = []
if isinstance(rows, list):
    for row in rows:
        if str(row.get("status") or "").lower() == "pending":
            pending.append(
                (
                    row.get("run_at"),
                    row.get("action"),
                    row.get("application_record_id"),
                    row.get("id"),
                )
            )
pending.sort()
print("pending_count", len(pending))
for item in pending:
    print("PENDING", *item)
