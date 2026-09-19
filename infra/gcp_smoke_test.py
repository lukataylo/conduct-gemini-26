"""
Pre-demo check: is real GCP working right now? Runs the golden path in-process with
REAL_GCP=true — auto-grant bucket, escalate + approve dataset, close the project — and
prints every GCP audit event. Ends with Alex's access removed again.

    .venv/bin/python infra/gcp_smoke_test.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and not key.startswith("#"):
        os.environ.setdefault(key.strip(), value.strip())
os.environ["REAL_GCP"] = "true"
sys.path[:0] = [str(ROOT), str(ROOT / "backend-api")]

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from policy_engine_paths import usecase_demo as demo  # noqa: E402

client = TestClient(app)
resp = client.post("/requests", json={
    "id": "ignored",
    "requester": demo.REQUESTER.model_dump(),
    "task_description": "Build the ingestion pipeline for Project Atlas",
    "project": "atlas-migration",
    "resource_ids": ["bucket-analytics-raw", "bq-project-x-finance"],
    "requested_duration_days": 14,
}).json()
print("request:", [(r["resource_id"], r["status"]) for r in resp["results"]])

for r in resp["results"]:
    if r["status"] == "escalated":
        case = client.get("/escalations").json()[0]
        for approver in case["required_approver_ids"]:
            client.post(f"/escalations/{r['escalation_id']}/vote", json={
                "escalation_id": r["escalation_id"], "approver_id": approver, "approved": True,
            })

client.post("/projects/atlas-migration/close")

gcp_events = [e for e in client.get("/audit").json() if e["actor"] == "gcp-iam"]
for e in gcp_events:
    print(" ", "OK  " if e["payload"].get("verified") else "FAIL", e["detail"])
ok = len(gcp_events) == 4 and all(e["payload"].get("verified") for e in gcp_events)
print("PASS: grant + revoke verified on both resources" if ok else "FAIL: see above")
sys.exit(0 if ok else 1)
