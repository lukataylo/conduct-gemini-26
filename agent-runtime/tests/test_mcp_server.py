from datetime import datetime, timedelta, timezone

from mcp_server import tools_for_grants
from modal_app import handle_mcp_tools, handle_watch
from shared.schemas import Grant


def _grant(resource_id: str = "bucket-analytics-raw", *, revoked: bool = False, expired: bool = False) -> Grant:
    now = datetime.now(timezone.utc)
    return Grant(
        id="g-1",
        request_id="r-1",
        resource_id=resource_id,
        requester_id="u-newhire-1",
        expires_at=now - timedelta(days=1) if expired else now + timedelta(days=14),
        revoked=revoked,
    )


def test_no_tools_without_grants():
    assert tools_for_grants([]) == []


def test_gcs_tool_when_bucket_granted():
    tools = tools_for_grants([_grant()])
    assert len(tools) == 1
    assert tools[0]["name"] == "gcs_list_analytics_raw"
    assert tools[0]["grant_id"] == "g-1"
    assert "g-1" in tools[0]["description"]


def test_sql_never_exposed():
    assert tools_for_grants([_grant("sql-prod-primary")]) == []


def test_revoked_and_expired_hidden():
    assert tools_for_grants([_grant(revoked=True)]) == []
    assert tools_for_grants([_grant(expired=True)]) == []


def test_handle_mcp_tools_payload():
    out = handle_mcp_tools({"grants": [_grant().model_dump(mode="json")]})
    assert out["tools"][0]["resource_id"] == "bucket-analytics-raw"


def test_handle_watch_ready():
    out = handle_watch()
    assert out["ready"] is True
    assert out["sandbox_id"] == "local"
