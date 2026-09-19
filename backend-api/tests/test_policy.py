from fastapi.testclient import TestClient

import main
from shared.schemas import AccessContext, AccessRequest, DecisionType


def test_get_policy_returns_live_default():
    client = TestClient(main.app)
    resp = client.get("/policy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == main.LIVE_POLICY.id
    assert body["description"] == main.policy_engine.DEFAULT_POLICY.description
    assert "internal" in body["max_auto_grant_duration_days"]


def test_evaluate_uses_live_policy_and_attaches_demo_ticket():
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
    assert not request.context.active_jira_ticket
    out = main._evaluate_request(request)
    assert out["results"][0]["status"] == "granted"
    stored = main.REQUESTS[out["request_id"]]
    assert stored.context.active_jira_ticket == "ATLAS-142"


def test_evaluate_keeps_caller_ticket():
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
        context=AccessContext(active_jira_ticket="ATLAS-999"),
    )
    out = main._evaluate_request(request)
    stored = main.REQUESTS[out["request_id"]]
    assert stored.context.active_jira_ticket == "ATLAS-999"
    assert out["results"][0]["status"] == "granted"


def test_evaluate_passes_live_policy(monkeypatch):
    seen = {}

    def fake_evaluate(request, resources, policy=None, active_grants=None, now=None, **kw):
        seen["policy"] = policy
        seen["now"] = now
        seen["grants"] = list(active_grants or [])
        from shared.schemas import PolicyDecision

        return [
            PolicyDecision(
                request_id=request.id,
                resource_id="bucket-analytics-raw",
                decision=DecisionType.AUTO_GRANT,
                reason="stub",
                ttl_hours=24,
            )
        ]

    monkeypatch.setattr(main.policy_engine, "evaluate_request", fake_evaluate)
    alex = main.KNOWN_REQUESTERS["u-newhire-1"]
    request = AccessRequest(
        id="ignored",
        requester=alex,
        task_description="need analytics-raw",
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
    )
    main._evaluate_request(request)
    assert seen["policy"] is main.LIVE_POLICY
    assert seen["now"] is not None
