from fastapi.testclient import TestClient

import main
from console_agent import ConsoleTurn
from shared.schemas import AccessRequest, Requester

ALEX_ID = "u-newhire-1"
PRIYA_ID = "u-manager-1"
JORDAN_ID = "u-finance-owner-1"

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
DIRECTORY_TEXT = (
    "Export the full SAP customer directory so we can dump every account."
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
    if "customer directory" in low:
        ids.append("sap-customer-directory")
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


def test_list_scope_as_priya_includes_waiting_on_me():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Here is the queue.",
            tools_used=["list_scope"],
            request_result=deps.list_scope(),
        )

    main.AGENT_TURN_IMPL = runner
    main.PARSE_IMPL = _parse
    main._evaluate_request(_parse(BOTH_TEXT, main.KNOWN_REQUESTERS[ALEX_ID]))

    resp = _client().post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": "Who is waiting on me?",
            "focus_id": ALEX_ID,
            "page": "overview",
        },
    )
    assert resp.status_code == 200
    scope = resp.json()["request_result"]
    assert scope["grants"] == []
    assert scope["cases"] == []
    assert len(scope["waiting_on_me"]) == 1
    waiting = scope["waiting_on_me"][0]
    assert waiting["resource_id"] == "bq-project-x-finance"
    assert waiting["requester_id"] == ALEX_ID
    assert waiting["status"] == "pending"
    assert PRIYA_ID in waiting["required_approver_ids"]
    assert len(scope["focus_grants"]) == 1
    assert scope["focus_grants"][0]["resource_id"] == "bucket-analytics-raw"
    assert len(scope["focus_cases"]) == 1
    assert scope["focus_cases"][0]["resource_id"] == "bq-project-x-finance"


def test_history_is_stored_and_actor_change_resets_conversation():
    seen: list[dict] = []

    def runner(message, deps, system_prompt):
        seen.append(
            {
                "history": list(deps.history),
                "page": deps.context.page if deps.context else None,
                "role": deps.context.role if deps.context else None,
                "actor_id": deps.context.actor_id if deps.context else None,
                "focus_id": deps.focus.id if deps.focus else None,
            }
        )
        return ConsoleTurn(reply=f"ack {len(seen)}", tools_used=[])

    main.AGENT_TURN_IMPL = runner
    client = _client()

    first = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "hello", "conversation_id": "c-hist", "page": "overview"},
    )
    assert first.status_code == 200
    assert first.json()["conversation_id"] == "c-hist"
    slot = main.CONVERSATIONS["c-hist"]
    assert slot["actor_id"] == ALEX_ID
    assert slot["messages"][0] == {"role": "user", "content": "hello"}
    assert slot["messages"][1]["role"] == "assistant"
    assert seen[0]["history"] == []
    assert seen[0]["page"] == "overview"
    assert seen[0]["role"] == "user"
    assert seen[0]["actor_id"] == ALEX_ID

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": ALEX_ID,
            "message": "follow up",
            "conversation_id": "c-hist",
            "focus_id": "Jordan Lee",
            "page": "timeline",
        },
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == "c-hist"
    assert len(seen[1]["history"]) == 2
    assert seen[1]["history"][0]["content"] == "hello"
    assert seen[1]["page"] == "timeline"
    assert seen[1]["focus_id"] == JORDAN_ID
    assert seen[1]["role"] == "user"

    stolen = client.post(
        "/agent/turn",
        json={"viewer_id": PRIYA_ID, "message": "now I am priya", "conversation_id": "c-hist"},
    )
    assert stolen.status_code == 200
    new_cid = stolen.json()["conversation_id"]
    assert new_cid != "c-hist"
    assert main.CONVERSATIONS["c-hist"]["actor_id"] == ALEX_ID
    assert main.CONVERSATIONS[new_cid]["actor_id"] == PRIYA_ID
    assert seen[2]["history"] == []
    assert seen[2]["role"] == "manager"

    main.CONVERSATIONS["c-hist"]["messages"] = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(45)
    ]
    trimmed = client.post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": "trim me", "conversation_id": "c-hist"},
    )
    assert trimmed.status_code == 200
    assert trimmed.json()["conversation_id"] == "c-hist"
    assert len(seen[-1]["history"]) == 20
    assert len(main.CONVERSATIONS["c-hist"]["messages"]) == 40


def test_policy_routes_split_gcp_and_sap():
    resp = _client().get("/policy/routes")
    assert resp.status_code == 200
    body = resp.json()
    gcp_ids = {row["id"] for row in body["gcp"]}
    sap_ids = {row["id"] for row in body["sap"]}
    assert "bucket-analytics-raw" in gcp_ids
    assert "bq-project-x-finance" in gcp_ids
    assert "sql-prod-primary" in gcp_ids
    assert "sap-bp-display" in sap_ids
    assert "sap-customer-directory" in sap_ids
    assert not gcp_ids & sap_ids
    assert all(not rid.startswith("sap-") for rid in gcp_ids)
    assert all(rid.startswith("sap-") for rid in sap_ids)
    finance = next(row for row in body["gcp"] if row["id"] == "bq-project-x-finance")
    assert finance["name"] == "project-x-finance"
    assert set(finance["approver_ids"]) == {PRIYA_ID, JORDAN_ID}
    for row in body["gcp"] + body["sap"]:
        assert set(row) == {"id", "name", "approver_ids"}


def _sponsor_jordan(message, deps, system_prompt):
    return ConsoleTurn(
        reply="Confirm sponsoring Jordan.",
        tools_used=["request_access_for"],
        request_result=deps.request_access_for(JORDAN_ID, message),
    )


def _sponsor_alex(message, deps, system_prompt):
    return ConsoleTurn(
        reply="Confirm sponsoring Alex.",
        tools_used=["request_access_for"],
        request_result=deps.request_access_for(ALEX_ID, message),
    )


def test_sponsor_jordan_bucket_grant_is_jordans_audit_is_priya():
    main.AGENT_TURN_IMPL = _sponsor_jordan
    client = _client()
    first = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": BUCKET_TEXT,
            "conversation_id": "c-sponsor-bucket",
            "focus_id": JORDAN_ID,
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["request_result"]["status"] == "needs_confirmation"
    preview = body["request_result"]["preview"]
    assert preview["beneficiary_id"] == JORDAN_ID
    assert preview["sponsored_by"] == PRIYA_ID
    assert preview["resource_ids"] == ["bucket-analytics-raw"]
    assert main.GRANTS == {}
    assert "Grant(" not in str(body["request_result"])

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": BUCKET_TEXT,
            "conversation_id": "c-sponsor-bucket",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    result = second.json()["request_result"]
    assert result["status"] == "evaluated"
    stored = main.REQUESTS[result["request_id"]]
    assert stored.requester.id == JORDAN_ID
    assert stored.metadata["sponsored_by"] == PRIYA_ID
    received = [
        event
        for event in main.AUDIT_LOG
        if event.type == main.AuditEventType.REQUEST_RECEIVED and event.request_id == result["request_id"]
    ]
    assert received
    assert received[0].actor == PRIYA_ID
    assert received[0].payload["beneficiary_id"] == JORDAN_ID
    assert not any(grant.requester_id == PRIYA_ID for grant in main.GRANTS.values())
    for grant in main.GRANTS.values():
        assert grant.requester_id == JORDAN_ID
    by_id = {row["resource_id"]: row for row in result["results"]}
    bucket = by_id["bucket-analytics-raw"]
    if bucket["status"] == "granted":
        assert main.GRANTS[bucket["grant_id"]].requester_id == JORDAN_ID
    else:
        assert bucket["status"] == "escalated"
        case = main.ESCALATIONS[bucket["escalation_id"]]
        assert case.requester_id == JORDAN_ID
        # Priya is the only catalog approver; omitting the sponsor would empty the list.
        assert case.required_approver_ids == [PRIYA_ID]


def test_sponsor_alex_bucket_auto_grant_belongs_to_alex():
    main.AGENT_TURN_IMPL = _sponsor_alex
    client = _client()
    first = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": BUCKET_TEXT,
            "conversation_id": "c-sponsor-alex-bucket",
            "focus_id": ALEX_ID,
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["request_result"]["status"] == "needs_confirmation"
    preview = body["request_result"]["preview"]
    assert preview["beneficiary_id"] == ALEX_ID
    assert preview["sponsored_by"] == PRIYA_ID
    assert preview["resource_ids"] == ["bucket-analytics-raw"]
    assert main.GRANTS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": BUCKET_TEXT,
            "conversation_id": "c-sponsor-alex-bucket",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    result = second.json()["request_result"]
    assert result["status"] == "evaluated"
    stored = main.REQUESTS[result["request_id"]]
    assert stored.requester.id == ALEX_ID
    assert stored.metadata["sponsored_by"] == PRIYA_ID
    by_id = {row["resource_id"]: row for row in result["results"]}
    bucket = by_id["bucket-analytics-raw"]
    assert bucket["status"] == "granted"
    grant = main.GRANTS[bucket["grant_id"]]
    assert grant.requester_id == ALEX_ID
    assert grant.resource_id == "bucket-analytics-raw"
    assert not any(row.requester_id == PRIYA_ID for row in main.GRANTS.values())
    received = [
        event
        for event in main.AUDIT_LOG
        if event.type == main.AuditEventType.REQUEST_RECEIVED and event.request_id == result["request_id"]
    ]
    assert received
    assert received[0].actor == PRIYA_ID
    assert received[0].payload["beneficiary_id"] == ALEX_ID


def test_sponsor_finance_omits_priya_from_required_approvers():
    main.AGENT_TURN_IMPL = _sponsor_jordan
    client = _client()
    first = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": FINANCE_TEXT,
            "conversation_id": "c-sponsor-finance",
            "focus_id": JORDAN_ID,
        },
    )
    assert first.status_code == 200
    assert first.json()["request_result"]["status"] == "needs_confirmation"
    assert first.json()["request_result"]["preview"]["sponsored_by"] == PRIYA_ID
    assert main.ESCALATIONS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": FINANCE_TEXT,
            "conversation_id": "c-sponsor-finance",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    rows = second.json()["request_result"]["results"]
    assert rows[0]["resource_id"] == "bq-project-x-finance"
    assert rows[0]["status"] == "escalated"
    case = main.ESCALATIONS[rows[0]["escalation_id"]]
    assert case.requester_id == JORDAN_ID
    assert PRIYA_ID not in case.required_approver_ids
    assert case.required_approver_ids == [JORDAN_ID]


def test_sponsor_directory_denied_no_grant():
    main.AGENT_TURN_IMPL = _sponsor_jordan
    client = _client()
    first = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": DIRECTORY_TEXT,
            "conversation_id": "c-sponsor-dir",
            "focus_id": JORDAN_ID,
        },
    )
    assert first.status_code == 200
    assert first.json()["request_result"]["status"] == "needs_confirmation"
    assert first.json()["request_result"]["preview"]["resource_ids"] == ["sap-customer-directory"]
    assert main.GRANTS == {}

    second = client.post(
        "/agent/turn",
        json={
            "viewer_id": PRIYA_ID,
            "message": DIRECTORY_TEXT,
            "conversation_id": "c-sponsor-dir",
            "confirm": True,
        },
    )
    assert second.status_code == 200
    rows = second.json()["request_result"]["results"]
    assert rows[0]["resource_id"] == "sap-customer-directory"
    assert rows[0]["status"] == "denied"
    assert main.GRANTS == {}
    assert not any(grant.resource_id == "sap-customer-directory" for grant in main.GRANTS.values())
