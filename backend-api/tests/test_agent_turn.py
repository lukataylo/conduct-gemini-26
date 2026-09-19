from fastapi.testclient import TestClient

import main
from console_agent import ConsoleTurn
from shared.schemas import AccessRequest, Requester

ALEX_ID = "u-newhire-1"

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


def test_injected_agent_request_access_grants_bucket_and_escalates_finance():
    def runner(message, deps, system_prompt):
        payload = deps.request_access(message)
        return ConsoleTurn(
            reply="Submitted to policy.",
            tools_used=["request_access"],
            request_result=payload,
        )

    main.AGENT_TURN_IMPL = runner
    resp = _client().post(
        "/agent/turn",
        json={"viewer_id": ALEX_ID, "message": BOTH_TEXT, "conversation_id": "c-golden"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "c-golden"
    assert body["tools_used"] == ["request_access"]
    result = body["request_result"]
    assert result["status"] == "evaluated"
    by_id = {row["resource_id"]: row for row in result["results"]}
    assert by_id["bucket-analytics-raw"]["status"] == "granted"
    assert by_id["bq-project-x-finance"]["status"] == "escalated"
    assert result["request_id"] in main.REQUESTS
    assert any(g.resource_id == "bucket-analytics-raw" for g in main.GRANTS.values())
    assert any(c.resource_id == "bq-project-x-finance" for c in main.ESCALATIONS.values())


def test_sql_critical_goes_through_policy_not_client_ids():
    def runner(message, deps, system_prompt):
        return ConsoleTurn(
            reply="Submitted.",
            tools_used=["request_access"],
            request_result=deps.request_access(message),
        )

    main.AGENT_TURN_IMPL = runner
    resp = _client().post("/agent/turn", json={"viewer_id": ALEX_ID, "message": SQL_TEXT})
    assert resp.status_code == 200
    rows = resp.json()["request_result"]["results"]
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
