from fastapi.testclient import TestClient

import main


def test_get_policy_matches_live_rule():
    client = TestClient(main.app)
    body = client.get("/policy").json()
    assert body["id"] == main.LIVE_POLICY.id
    assert body["max_auto_grant_duration_days"]["internal"] == 30
    assert "critical" in [t.lower() for t in body.get("always_escalate_tiers", [])]


def test_add_person_then_request_as_them():
    client = TestClient(main.app)
    created = client.post("/people", json={"name": "Sam Rivera", "team": "growth"})
    assert created.status_code == 200
    person = created.json()
    assert person["id"] == "u-sam-rivera"
    assert person["team"] == "growth"
    assert person["manager_id"] == "u-manager-1"
    listed = {p["id"] for p in client.get("/people").json()}
    assert "u-sam-rivera" in listed
    again = client.post("/people", json={"name": "Sam Rivera", "team": "growth"})
    assert again.status_code == 409


def test_demo_seed_fills_the_console_snapshot():
    client = TestClient(main.app)
    seeded = client.post("/demo/seed")
    assert seeded.status_code == 200
    counts = seeded.json()
    assert counts["grants"] >= 3
    assert counts["cases"] >= 1
    assert counts["events"] >= 8

    grants = client.get("/grants?include_revoked=true").json()
    people = {p["id"] for p in client.get("/people").json()}
    assert {"u-newhire-1", "u-manager-1", "u-finance-owner-1"} <= people
    alex_active = [
        g
        for g in grants
        if g["requester_id"] == "u-newhire-1" and not g["revoked"]
    ]
    assert {g["resource_id"] for g in alex_active} >= {
        "bucket-analytics-raw",
        "repo-atlas-ingestion",
    }
    priya_revoked = [
        g
        for g in grants
        if g["requester_id"] == "u-manager-1" and g["revoked"]
    ]
    assert priya_revoked
    cases = client.get("/escalations?status=pending").json()
    assert any(c["resource_id"] == "bq-project-x-finance" for c in cases)
    assert any(c["resource_id"] == "sql-prod-primary" for c in cases)
    events = client.get("/audit").json()
    bounced = [
        e
        for e in events
        if e["type"] == "action_executed" and e["payload"].get("status") == "bounced"
    ]
    assert bounced
    tools = client.get("/tools", params={"requester_id": "u-newhire-1"}).json()
    names = {t["name"] for t in tools}
    assert "gcs_list_analytics_raw" in names
    assert "gh_push_atlas_ingestion" in names
    assert "bq_query_project_x_finance" not in names
