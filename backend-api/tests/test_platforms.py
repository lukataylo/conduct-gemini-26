from fastapi.testclient import TestClient

import main
from shared.schemas import AccessContext, AccessRequest, Grant


def test_get_company_is_atlas():
    body = TestClient(main.app).get("/company").json()
    assert body["id"] == "atlas"
    assert body["name"] == "Atlas"
    assert body["project"] == "atlas-migration"
    by_id = {row["id"]: row for row in body["platforms"]}
    assert by_id["gcp"]["name"] == "Google Cloud"
    assert by_id["gcp"]["short"] == "GCP"
    assert by_id["gcp"]["home"] is True
    assert by_id["sap"]["name"] == "SAP S/4HANA"
    assert by_id["sap"]["short"] == "SAP"
    assert by_id["sap"]["home"] is False


def test_alex_sales_order_denied_without_sap():
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    assert alex.platforms == ["gcp"]
    out = main._evaluate_request(
        AccessRequest(
            id="ignored",
            requester=alex,
            task_description="need sales order display",
            project="atlas-migration",
            resource_ids=["sap-sales-order-display"],
            requested_duration_days=3,
            raw_text="need sales order display",
            context=AccessContext(active_jira_ticket="INC-8841"),
        )
    )
    row = out["results"][0]
    assert row["resource_id"] == "sap-sales-order-display"
    assert row["status"] == "denied"
    assert "Atlas-Platform-01" in row["reason"]
    assert "SAP" in row["reason"]


def test_grant_sap_to_alex_then_sales_order_can_grant():
    client = TestClient(main.app)
    granted = client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "grant"})
    assert granted.status_code == 200
    assert granted.json()["platforms"] == ["gcp", "sap"]
    assert any(
        g["resource_id"] == "platform-sap" and not g["revoked"]
        for g in client.get("/grants", params={"requester_id": "u-newhire-1"}).json()
    )

    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    out = main._evaluate_request(
        AccessRequest(
            id="ignored",
            requester=alex,
            task_description="need sales order display",
            project="atlas-migration",
            resource_ids=["sap-sales-order-display"],
            requested_duration_days=3,
            raw_text="need sales order display",
            context=AccessContext(active_jira_ticket="INC-8841"),
        )
    )
    row = out["results"][0]
    assert row["resource_id"] == "sap-sales-order-display"
    assert row["status"] == "granted"
    assert row["grant_id"]

    revoked = client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "revoke"})
    assert revoked.status_code == 200
    assert revoked.json()["platforms"] == ["gcp"]
    assert not any(
        g["resource_id"] == "platform-sap" and not g["revoked"]
        for g in client.get("/grants", params={"requester_id": "u-newhire-1"}).json()
    )


def test_maya_analytics_bucket_denied_without_gcp():
    maya = main.KNOWN_REQUESTERS["u-sales-1"]
    assert maya.platforms == ["sap"]
    out = main._evaluate_request(
        AccessRequest(
            id="ignored",
            requester=maya,
            task_description="need analytics-raw",
            project="atlas-migration",
            resource_ids=["bucket-analytics-raw"],
            requested_duration_days=1,
            raw_text="need analytics-raw",
            context=AccessContext(active_jira_ticket="ATLAS-142"),
        )
    )
    row = out["results"][0]
    assert row["resource_id"] == "bucket-analytics-raw"
    assert row["status"] == "denied"
    assert "Atlas-Platform-01" in row["reason"]
    assert "GCP" in row["reason"]


def test_platform_grants_are_not_enqueued():
    seen: list[tuple[str, str]] = []
    main.EXECUTE_ENQUEUE_IMPL = lambda grant, action="grant", ask=None: seen.append((grant.resource_id, action))

    client = TestClient(main.app)
    granted = client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "grant"})
    assert granted.status_code == 200
    assert all(resource_id != "platform-sap" for resource_id, _ in seen)
    assert ("sap-bp-display", "grant") in seen

    seen.clear()
    client.post("/people/u-newhire-1/platforms", json={"platform": "sap", "action": "revoke"})
    assert ("sap-bp-display", "revoke") in seen
    assert all(resource_id != "platform-sap" for resource_id, _ in seen)

    seen.clear()
    now = main.now()
    main._enqueue_execute(
        Grant(
            id="g-platform-gcp",
            request_id="r-platform",
            resource_id="platform-gcp",
            requester_id="u-newhire-1",
            granted_at=now,
            expires_at=now,
        )
    )
    assert seen == []
    assert main.EXECUTE_ENQUEUE_IMPL is not None
