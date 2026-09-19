from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

import main
from shared.schemas import AccessRequest, Grant

CONSOLE_HTML = Path(__file__).resolve().parents[2] / "agent-runtime" / "mock_console" / "index.html"


def test_console_state_binds_active_bucket_grant():
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
        raw_text="need analytics-raw",
    )
    out = main._evaluate_request(request)
    assert out["results"][0]["status"] == "granted"
    grant_id = out["results"][0]["grant_id"]

    client = TestClient(main.app)
    resp = client.get("/console/state")
    assert resp.status_code == 200
    body = resp.json()
    assert {r["id"] for r in body["resources"]} == set(main.usecase_demo.RESOURCES)
    assert len(body["bindings"]) == 1
    binding = body["bindings"][0]
    assert binding["principal"] == "u-newhire-1"
    assert binding["role"] == "Storage Object Viewer"
    assert binding["resource_id"] == "bucket-analytics-raw"
    assert binding["grant_id"] == grant_id
    assert binding["expires_at"]


def test_console_state_uses_active_grants_and_github_roles():
    future = main.now() + timedelta(days=1)
    past = main.now() - timedelta(hours=1)
    main.GRANTS["g-write"] = Grant(
        id="g-write",
        request_id="r-write",
        resource_id="repo-atlas-ingestion",
        requester_id="u-newhire-1",
        expires_at=future,
    )
    main.GRANTS["g-read"] = Grant(
        id="g-read",
        request_id="r-read",
        resource_id="repo-finance-ledger",
        requester_id="u-newhire-1",
        expires_at=future,
    )
    main.GRANTS["g-sql"] = Grant(
        id="g-sql",
        request_id="r-sql",
        resource_id="sql-prod-primary",
        requester_id="u-newhire-1",
        expires_at=future,
    )
    main.GRANTS["g-bq"] = Grant(
        id="g-bq",
        request_id="r-bq",
        resource_id="bq-project-x-finance",
        requester_id="u-newhire-1",
        expires_at=future,
    )
    main.GRANTS["g-revoked"] = Grant(
        id="g-revoked",
        request_id="r-revoked",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=future,
        revoked=True,
    )
    main.GRANTS["g-expired"] = Grant(
        id="g-expired",
        request_id="r-expired",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=past,
    )

    body = TestClient(main.app).get("/console/state").json()
    roles = {binding["resource_id"]: binding["role"] for binding in body["bindings"]}
    assert roles == {
        "repo-atlas-ingestion": "Write",
        "repo-finance-ledger": "Triage",
        "sql-prod-primary": "Cloud SQL Client",
        "bq-project-x-finance": "BigQuery Data Viewer",
    }
    assert all(binding["principal"] == "u-newhire-1" for binding in body["bindings"])


def test_mock_console_hydrates_from_backend_state():
    text = CONSOLE_HTML.read_text()
    assert "URLSearchParams" in text
    assert "CONSOLE_BACKEND" in text
    assert "/console/state" in text
    assert "hydrateFromBackend" in text
    assert 'id="active-grants"' in text
