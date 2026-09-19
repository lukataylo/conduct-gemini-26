from fastapi.testclient import TestClient

import main
from console_agent import ConsoleTurn
from shared.schemas import AccessRequest, Requester

ALEX_ID = "u-newhire-1"
PRIYA_ID = "u-manager-1"

BUCKET_TEXT = (
    "Need read on the analytics-raw GCS bucket so I can inspect last week's "
    "ingest for the data-platform onboarding task. Two weeks is enough."
)
FINANCE_TEXT = (
    "I need the project-x-finance BigQuery dataset to reconcile Atlas invoice "
    "lines. I'm on data-platform, done by Nov 15."
)
BOTH_TEXT = (
    "Need read on the analytics-raw GCS bucket so I can inspect last week's "
    "ingest, and the project-x-finance BigQuery dataset to reconcile Atlas "
    "invoice lines. Two weeks is enough."
)
SQL_TEXT = (
    "Grant me access to the prod-primary Cloud SQL instance so I can patch a "
    "customer row. Need it today."
)
CLOSE_TEXT = "Revoke everything and shut Atlas down."


def _parse(raw_text: str, requester: Requester) -> AccessRequest:
    ids: list[str] = []
    low = raw_text.lower()
    if "analytics-raw" in low or "gcs bucket" in low:
        ids.append("bucket-analytics-raw")
    if "finance" in low or "project-x" in low:
        ids.append("bq-project-x-finance")
    if "prod-primary" in low or "cloud sql" in low:
        ids.append("sql-prod-primary")
    days = 14
    if "today" in low:
        days = 1
    return AccessRequest(
        id="client-ignored",
        requester=requester,
        task_description=raw_text,
        project="atlas-migration",
        resource_ids=ids,
        requested_duration_days=days,
        raw_text=raw_text,
    )


def _client() -> TestClient:
    main.PARSE_IMPL = _parse
    return TestClient(main.app)


def test_unknown_viewer_is_400():
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": "no-such-user", "message": "hello"},
    )
    assert resp.status_code == 400
    assert "unknown requester" in resp.json()["detail"]


def test_request_access_needs_confirmation_before_evaluate():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Confirm this request.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    client = _client()
    first = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": BOTH_TEXT, "conversation_id": "c-confirm"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["request_result"]["status"] == "needs_confirmation"
    preview = body["request_result"]["preview"]
    assert preview["resource_ids"] == ["bucket-analytics-raw", "bq-project-x-finance"]
    assert preview["project"] == "atlas-migration"
    assert preview["requested_duration_days"] == 14
    assert main.GRANTS == {}
    assert main.ESCALATIONS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": ALEX_ID,
            "message": BOTH_TEXT,
            "conversation_id": "c-confirm",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    result = second.json()["request_result"]
    assert result["status"] == "evaluated"
    by_id = {row["resource_id"]: row for row in result["results"]}
    assert by_id["bucket-analytics-raw"]["status"] == "granted"
    assert by_id["bq-project-x-finance"]["status"] == "escalated"
    assert any(g.resource_id == "bucket-analytics-raw" for g in main.GRANTS.values())


def test_confirm_without_pending_is_400():
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "ok", "confirm": True, "conversation_id": "c-none"},
    )
    assert resp.status_code == 400
    assert "nothing to confirm" in resp.json()["detail"]


def test_confirm_from_other_viewer_is_400():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Confirm this request.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    client = _client()
    first = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": BOTH_TEXT, "conversation_id": "c-bind"},
    )
    assert first.status_code == 200
    assert first.json()["request_result"]["status"] == "needs_confirmation"

    stolen = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": BOTH_TEXT,
            "conversation_id": "c-bind",
            "confirm": True,
        },
    )
    assert stolen.status_code == 400
    detail = stolen.json()["detail"].lower()
    assert "not for this viewer" in detail
    assert "nothing to confirm" in detail
    assert main.GRANTS == {}
    assert main.ESCALATIONS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": ALEX_ID,
            "message": BOTH_TEXT,
            "conversation_id": "c-bind",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    result = second.json()["request_result"]
    assert result["status"] == "evaluated"
    by_id = {row["resource_id"]: row for row in result["results"]}
    assert by_id["bucket-analytics-raw"]["status"] == "granted"
    assert by_id["bq-project-x-finance"]["status"] == "escalated"


def test_sql_critical_goes_through_policy_not_client_ids():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Submitted.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    client = _client()
    first = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": SQL_TEXT, "conversation_id": "c-sql"},
    )
    assert first.status_code == 200
    assert first.json()["request_result"]["status"] == "needs_confirmation"
    assert main.GRANTS == {}
    assert main.ESCALATIONS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": ALEX_ID,
            "message": SQL_TEXT,
            "conversation_id": "c-sql",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    rows = second.json()["request_result"]["results"]
    assert rows[0]["resource_id"] == "sql-prod-primary"
    assert rows[0]["status"] == "escalated"  # CRITICAL always_escalate_tiers


def test_refuse_close_does_not_close_project():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(reply="I cannot close Atlas or revoke grants.", tools_used=[])

    main.AGENT_TURN_IMPL = runner
    # seed a grant via the real evaluate path so close would have something to revoke
    main.PARSE_IMPL = _parse
    seeded = main._evaluate_request(_parse(BUCKET_TEXT, main.KNOWN_REQUESTERS[ALEX_ID]))
    assert seeded["results"][0]["status"] == "granted"
    before = dict(main.GRANTS)

    resp = _client().post("/agent/turn", json={"viewer_id": ALEX_ID, "message": CLOSE_TEXT})
    assert resp.status_code == 200
    assert resp.json()["tools_used"] == []
    assert main.GRANTS.keys() == before.keys()
    assert all(not g.revoked for g in main.GRANTS.values())


def test_list_scope_is_viewer_active_and_pending_only():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Here is your scope.",
            tools_used=["list_scope"],
            request_result=deps.list_scope(),
        )

    main.AGENT_TURN_IMPL = runner
    main.PARSE_IMPL = _parse
    main._evaluate_request(_parse(BOTH_TEXT, main.KNOWN_REQUESTERS[ALEX_ID]))

    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "What do I currently have, and why is finance still pending?"},
    )
    body = resp.json()
    assert body["tools_used"] == ["list_scope"]
    scope = body["request_result"]
    assert len(scope["grants"]) == 1
    assert scope["grants"][0]["resource_id"] == "bucket-analytics-raw"
    assert len(scope["cases"]) == 1
    assert scope["cases"][0]["resource_id"] == "bq-project-x-finance"
    assert scope["cases"][0]["status"] == "pending"


def test_explain_decision_does_not_leak_other_viewer():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Here is why.",
            tools_used=["explain_decision"],
            request_result=deps.explain_decision(),
        )

    main.AGENT_TURN_IMPL = runner
    main.PARSE_IMPL = _parse
    alex = main.KNOWN_REQUESTERS[ALEX_ID]
    priya = main.KNOWN_REQUESTERS[PRIYA_ID]
    alex_eval = main._evaluate_request(_parse(BUCKET_TEXT, alex))
    priya_eval = main._evaluate_request(_parse(FINANCE_TEXT, priya))
    priya_details = {
        e.detail
        for e in main.AUDIT_LOG
        if e.type == main.AuditEventType.POLICY_EVALUATED and e.request_id == priya_eval["request_id"]
    }
    alex_details = {
        e.detail
        for e in main.AUDIT_LOG
        if e.type == main.AuditEventType.POLICY_EVALUATED and e.request_id == alex_eval["request_id"]
    }
    assert priya_details
    assert alex_details

    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "Why was that decided?"},
    )
    assert resp.status_code == 200
    explanation = resp.json()["request_result"]["explanation"]
    assert explanation not in priya_details
    assert explanation in alex_details or explanation == "No typed policy decision found for that id."

    leaked = main._console_explain_decision(alex)
    assert leaked["explanation"] not in priya_details
    assert leaked["explanation"] in alex_details
