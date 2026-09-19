from datetime import timedelta

from fastapi.testclient import TestClient

import main
from shared.schemas import AccessRequest


def _issue_short_grant() -> str:
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
    grant = main.GRANTS[grant_id]
    main.GRANTS[grant_id] = grant.model_copy(update={"expires_at": main.now() + timedelta(hours=1)})
    return grant_id


def test_clock_advance_leaves_grant_until_sweep_revokes():
    captured: list[str] = []

    def impl(grant, action="grant"):
        captured.append(action)

    main.EXECUTE_ENQUEUE_IMPL = impl
    grant_id = _issue_short_grant()

    client = TestClient(main.app)
    active = client.get("/grants").json()
    assert any(g["id"] == grant_id for g in active)

    resp = client.post("/clock/advance", json={"days": 14})
    assert resp.status_code == 200
    body = resp.json()
    assert "now" in body
    assert body["offset_days"] == 14
    assert any(
        e.actor == "policy-engine" and e.detail == "advanced 14d" for e in main.AUDIT_LOG
    )

    listed = client.get("/grants", params={"include_revoked": True}).json()
    assert any(g["id"] == grant_id and not g["revoked"] for g in listed)
    assert not main.GRANTS[grant_id].revoked

    revoked_ids = main.sweep_expired()
    assert grant_id in revoked_ids
    grant = main.GRANTS[grant_id]
    assert grant.revoked is True
    assert grant.revoked_reason == "expired"
    assert "revoke" in captured
