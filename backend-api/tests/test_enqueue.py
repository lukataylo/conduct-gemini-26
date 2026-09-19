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
