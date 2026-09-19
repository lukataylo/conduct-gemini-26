from datetime import datetime, timedelta, timezone

import main
from shared.schemas import Grant


def test_enqueue_local_passes_action(monkeypatch):
    seen: dict = {}

    class Immediate:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    def fake_execute(grant, console, *, watch_url=None, callback_base_url=None, action="grant"):
        seen["action"] = action
        seen["grant_id"] = grant.id
        seen["console"] = console

    monkeypatch.setenv("AGENT_RUNTIME_LOCAL_EXECUTE", "true")
    monkeypatch.delenv("AGENT_RUNTIME_EXECUTE_URL", raising=False)
    monkeypatch.setattr(main.threading, "Thread", Immediate)
    monkeypatch.setattr("computer_use.execute_grant", fake_execute)

    now = datetime.now(timezone.utc)
    grant = Grant(
        id="g-enqueue",
        request_id="r-enqueue",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )
    main._enqueue_execute(grant, action="browse")
    assert seen["action"] == "browse"
    assert seen["grant_id"] == "g-enqueue"


def test_enqueue_forwards_ask():
    seen: dict = {}

    def impl(grant, action="grant", ask=None):
        seen["grant_id"] = grant.id
        seen["action"] = action
        seen["ask"] = ask

    main.EXECUTE_ENQUEUE_IMPL = impl
    now = datetime.now(timezone.utc)
    grant = Grant(
        id="g-ask",
        request_id="r-ask",
        resource_id="bq-project-x-finance",
        requester_id="u-finance-owner-1",
        granted_at=now,
        expires_at=now + timedelta(days=14),
    )
    main._enqueue_execute(grant, action="query", ask="invoice lines for Atlas")
    assert seen["grant_id"] == "g-ask"
    assert seen["action"] == "query"
    assert seen["ask"] == "invoice lines for Atlas"


def test_enqueue_export_directory_despite_never_enact():
    seen: list[tuple] = []

    def impl(grant, action="grant", ask=None):
        seen.append((grant.resource_id, action, ask))

    main.EXECUTE_ENQUEUE_IMPL = impl
    now = datetime.now(timezone.utc)
    grant = Grant(
        id="g-dir-export",
        request_id="r-dir",
        resource_id="sap-customer-directory",
        requester_id="u-finance-owner-1",
        granted_at=now,
        expires_at=now + timedelta(days=1),
    )
    main._enqueue_execute(grant)
    assert seen == []
    main._enqueue_execute(grant, action="export", ask="export every account")
    assert seen == [("sap-customer-directory", "export", "export every account")]
