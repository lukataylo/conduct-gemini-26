from fastapi.testclient import TestClient

import main

ALEX_ID = "u-newhire-1"
PRIYA_ID = "u-manager-1"
JORDAN_ID = "u-finance-owner-1"


def _client() -> TestClient:
    return TestClient(main.app)


def _seen() -> list[dict]:
    rows: list[dict] = []

    def impl(grant, action="grant", ask=None):
        rows.append(
            {
                "grant_id": grant.id,
                "resource_id": grant.resource_id,
                "requester_id": grant.requester_id,
                "action": action,
                "ask": ask,
            }
        )

    main.EXECUTE_ENQUEUE_IMPL = impl
    return rows


def test_enact_manager_gcp_defaults_to_browse():
    seen = _seen()
    resp = _client().post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": ALEX_ID, "platform": "gcp"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "enqueued"
    assert body["action"] == "browse"
    assert body["resource_id"] == "bucket-analytics-raw"
    assert body["person_id"] == ALEX_ID
    assert body["grant_id"] is None
    assert seen == [
        {
            "grant_id": seen[0]["grant_id"],
            "resource_id": "bucket-analytics-raw",
            "requester_id": ALEX_ID,
            "action": "browse",
            "ask": body["ask"],
        }
    ]
    assert ALEX_ID not in {g.requester_id for g in main.GRANTS.values() if g.resource_id == "bucket-analytics-raw"}


def test_enact_uses_held_grant_id():
    seen = _seen()
    grant = main._issue_grant("r-alex-bucket", ALEX_ID, "bucket-analytics-raw", ttl_days=3)
    seen.clear()
    resp = _client().post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": ALEX_ID, "platform": "gcp", "action": "browse"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "enqueued"
    assert body["grant_id"] == grant.id
    assert seen[0]["grant_id"] == grant.id
    assert seen[0]["action"] == "browse"


def test_enact_query_and_sap_verbs():
    seen = _seen()
    client = _client()
    query = client.post(
        "/enact",
        json={"viewer_id": JORDAN_ID, "person_id": JORDAN_ID, "platform": "gcp", "action": "query"},
    )
    assert query.status_code == 200
    assert query.json()["action"] == "query"
    assert query.json()["resource_id"] == "bq-project-x-finance"

    inspect = client.post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": ALEX_ID, "platform": "sap", "action": "inspect"},
    )
    assert inspect.status_code == 200
    assert inspect.json()["action"] == "inspect"
    assert inspect.json()["resource_id"] == "sap-bp-display"

    export = client.post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": ALEX_ID, "platform": "sap", "action": "export"},
    )
    assert export.status_code == 200
    assert export.json()["grant_id"] is None
    assert export.json()["resource_id"] == "sap-customer-directory"
    assert [row["action"] for row in seen] == ["query", "inspect", "export"]


def test_enact_rejects_non_manager_and_mismatched_action():
    seen = _seen()
    client = _client()
    denied = client.post(
        "/enact",
        json={"viewer_id": ALEX_ID, "person_id": ALEX_ID, "platform": "gcp"},
    )
    assert denied.status_code == 403
    mismatch = client.post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": ALEX_ID, "platform": "gcp", "action": "inspect"},
    )
    assert mismatch.status_code == 400
    missing = client.post(
        "/enact",
        json={"viewer_id": PRIYA_ID, "person_id": "u-nobody", "platform": "gcp"},
    )
    assert missing.status_code == 400
    assert seen == []


def test_add_person_auto_enacts_selected_platforms():
    seen = _seen()
    created = _client().post(
        "/people",
        json={"name": "Sam Rivera", "team": "growth", "platforms": ["gcp", "sap"]},
    )
    assert created.status_code == 200
    assert created.json()["id"] == "u-sam-rivera"
    assert {(row["resource_id"], row["action"], row["requester_id"]) for row in seen} == {
        ("bucket-analytics-raw", "browse", "u-sam-rivera"),
        ("sap-bp-display", "inspect", "u-sam-rivera"),
    }
    assert not any(row["resource_id"].startswith("platform-") for row in seen)


def test_platform_grant_auto_enacts_use_not_platform_id():
    seen = _seen()
    client = _client()
    granted = client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "grant"})
    assert granted.status_code == 200
    assert all(row["resource_id"] != "platform-sap" for row in seen)
    assert ("sap-bp-display", "grant") in {(row["resource_id"], row["action"]) for row in seen}

    seen.clear()
    revoked = client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "revoke"})
    assert revoked.status_code == 200
    assert ("sap-bp-display", "revoke") in {(row["resource_id"], row["action"]) for row in seen}
    assert all(row["resource_id"] != "platform-sap" for row in seen)
