from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
from shared.schemas import AccessContext, AccessRequest, AuditEventType, Grant


SAP_RESOURCE_IDS = {
    "sap-bp-display",
    "sap-billing-display",
    "sap-sales-order-display",
    "sap-customer-directory",
    "sap-hr-payroll",
}


def _grant(resource_id: str, grant_id: str, *, revoked: bool = False, expired: bool = False) -> Grant:
    now = main.now()
    grant = Grant(
        id=grant_id,
        request_id=f"r-{grant_id}",
        resource_id=resource_id,
        requester_id="u-newhire-1",
        expires_at=now - timedelta(hours=1) if expired else now + timedelta(days=1),
        revoked=revoked,
    )
    main.GRANTS[grant_id] = grant
    return grant


def test_sap_state_lists_only_sap_resources_and_active_bindings():
    _grant("sap-bp-display", "g-sap-bp")
    _grant("bucket-analytics-raw", "g-bucket")
    _grant("sap-bp-display", "g-sap-revoked", revoked=True)
    _grant("sap-billing-display", "g-sap-expired", expired=True)

    client = TestClient(main.app)
    resp = client.get("/sap/state")
    assert resp.status_code == 200
    body = resp.json()

    assert {r["id"] for r in body["resources"]} == SAP_RESOURCE_IDS
    assert all(rid.startswith("sap-") for rid in (r["id"] for r in body["resources"]))

    assert len(body["bindings"]) == 1
    binding = body["bindings"][0]
    assert binding["resource_id"] == "sap-bp-display"
    assert binding["principal"] == "u-newhire-1"
    assert binding["role"] == "SAP_SD_CUST_DISPLAY"
    assert binding["company_code"] == "1000"
    assert binding["customer_id"] == "1710001"
    assert binding["activity"] == "03"
    assert binding["grant_id"] == "g-sap-bp"
    assert binding["expires_at"]


def test_console_state_bindings_exclude_sap_ids():
    _grant("sap-bp-display", "g-sap-bp")
    _grant("bucket-analytics-raw", "g-bucket")
    _grant("platform-sap", "g-platform-sap")

    body = TestClient(main.app).get("/console/state").json()
    assert {r["id"] for r in body["resources"]} == set(main.usecase_demo.RESOURCES)
    assert {b["resource_id"] for b in body["bindings"]} == {"bucket-analytics-raw"}
    assert all(not b["resource_id"].startswith("sap-") for b in body["bindings"])
    assert all(not b["resource_id"].startswith("platform-") for b in body["bindings"])


def test_console_url_for_routes_sap_and_gcp(monkeypatch):
    now = datetime.now(timezone.utc)
    sap = Grant(
        id="g-sap",
        request_id="r-sap",
        resource_id="sap-bp-display",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=1),
    )
    gcp = Grant(
        id="g-gcp",
        request_id="r-gcp",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=1),
    )
    monkeypatch.delenv("SAP_CONSOLE_URL", raising=False)
    monkeypatch.delenv("CONSOLE_URL", raising=False)
    assert main._console_url_for(sap) == "http://127.0.0.1:8766/"
    assert main._console_url_for(gcp) == "http://127.0.0.1:8765/"

    monkeypatch.setenv("SAP_CONSOLE_URL", "http://sap.example/")
    monkeypatch.setenv("CONSOLE_URL", "http://gcp.example/")
    assert main._console_url_for(sap) == "http://sap.example/"
    assert main._console_url_for(gcp) == "http://gcp.example/"


def test_enqueue_skips_never_enact_ids():
    seen: list[str] = []
    main.EXECUTE_ENQUEUE_IMPL = lambda grant, action="grant": seen.append(grant.resource_id)
    now = datetime.now(timezone.utc)
    for resource_id in ("sql-prod-primary", "sap-customer-directory", "sap-hr-payroll"):
        main._enqueue_execute(
            Grant(
                id=f"g-{resource_id}",
                request_id="r-skip",
                resource_id=resource_id,
                requester_id="u-newhire-1",
                granted_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
    assert seen == []
    assert main.NEVER_ENACT_IDS == frozenset(
        {"sql-prod-primary", "sap-customer-directory", "sap-hr-payroll"}
    )

    main._enqueue_execute(
        Grant(
            id="g-bp",
            request_id="r-ok",
            resource_id="sap-bp-display",
            requester_id="u-newhire-1",
            granted_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    assert seen == ["sap-bp-display"]


def test_enqueue_uses_sap_console_url(monkeypatch):
    seen: dict = {}

    class Immediate:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    def fake_execute(grant, console, *, watch_url=None, callback_base_url=None, action="grant"):
        seen["console"] = console
        seen["grant_id"] = grant.id

    monkeypatch.setenv("AGENT_RUNTIME_LOCAL_EXECUTE", "true")
    monkeypatch.delenv("AGENT_RUNTIME_EXECUTE_URL", raising=False)
    monkeypatch.delenv("SAP_CONSOLE_URL", raising=False)
    main._agent_runtime_on_path()
    monkeypatch.setattr(main.threading, "Thread", Immediate)
    monkeypatch.setattr("computer_use.execute_grant", fake_execute)

    now = datetime.now(timezone.utc)
    main._enqueue_execute(
        Grant(
            id="g-sap-url",
            request_id="r-sap-url",
            resource_id="sap-sales-order-display",
            requester_id="u-newhire-1",
            granted_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    assert seen["console"] == "http://127.0.0.1:8766/"
    assert seen["grant_id"] == "g-sap-url"


def test_export_demo_writes_bounced_action():
    client = TestClient(main.app)
    resp = client.post("/sap/export-demo")
    assert resp.status_code == 200
    assert resp.json() == {"status": "bounced", "grant_id": None}

    bounced = [
        e
        for e in main.AUDIT_LOG
        if e.type == AuditEventType.ACTION_EXECUTED and e.payload.get("status") == "bounced"
    ]
    assert len(bounced) == 1
    event = bounced[0]
    assert event.grant_id is None
    assert event.payload["tool"] == "sap_export_customer_list"
    assert event.payload["action"] == "export"
    assert event.payload["requester_id"] == "u-newhire-1"


def test_evaluate_sales_order_auto_grants_and_directory_denies():
    priya = main.KNOWN_REQUESTERS["u-manager-1"]
    request = AccessRequest(
        id="ignored",
        requester=priya,
        task_description="need sales order and customer directory",
        project="atlas-migration",
        resource_ids=["sap-sales-order-display", "sap-customer-directory"],
        requested_duration_days=3,
        raw_text="need sales order and customer directory",
        context=AccessContext(active_jira_ticket="INC-8841"),
    )
    out = main._evaluate_request(request)
    by_id = {row["resource_id"]: row for row in out["results"]}
    assert by_id["sap-sales-order-display"]["status"] == "granted"
    assert by_id["sap-sales-order-display"]["grant_id"]
    assert by_id["sap-customer-directory"]["status"] == "denied"
    assert "Conduct-SAP-01" in by_id["sap-customer-directory"]["reason"]
