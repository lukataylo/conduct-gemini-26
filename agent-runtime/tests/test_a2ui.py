from datetime import datetime, timedelta, timezone

from a2ui import CATALOG, compose_ui
from shared.schemas import EscalationCase, Grant, UIComponentSpec, UISpec


def _grant():
    now = datetime.now(timezone.utc)
    return Grant(
        id="g-1",
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=now + timedelta(days=14),
    )


def _case():
    return EscalationCase(
        id="c-1",
        request_id="r-1",
        resource_id="bq-project-x-finance",
        required_approver_ids=["u-manager-1"],
        requester_id="u-newhire-1",
        requested_duration_days=14,
    )


def test_catalog_is_fixed():
    assert CATALOG == (
        "GrantCard",
        "PendingApprovalCard",
        "AuditTimeline",
        "ConsoleWatchCard",
    )


def test_fallback_requester_layout():
    spec = compose_ui([_grant()], [_case()], "requester", viewer_id="u-newhire-1")
    names = [p.component for p in spec.panels]
    assert "GrantCard" in names
    assert "PendingApprovalCard" in names
    assert spec.panels[0].id == "grant-g-1"


def test_drops_off_catalog_from_runner():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="x", component="EvilWidget", props={"grant_id": "g-1"}),
                UIComponentSpec(id="grant-g-1", component="GrantCard", props={"grant_id": "g-1", "resource_id": "bucket-analytics-raw"}),
            ],
        )

    spec = compose_ui([_grant()], [], "requester", viewer_id="u-newhire-1", runner=runner)
    assert all(p.component in CATALOG for p in spec.panels)
    assert all(p.component != "EvilWidget" for p in spec.panels)


def test_drops_panels_not_in_viewer_set():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="grant-g-1", component="GrantCard", props={"grant_id": "g-1"}),
                UIComponentSpec(id="grant-other", component="GrantCard", props={"grant_id": "g-other"}),
            ],
        )

    spec = compose_ui([_grant()], [], "requester", viewer_id="u-newhire-1", runner=runner)
    assert [p.props.get("grant_id") for p in spec.panels] == ["g-1"]


def test_drops_cases_not_in_viewer_set():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(
                    id="case-c-1",
                    component="PendingApprovalCard",
                    props={"escalation_id": "c-1"},
                ),
                UIComponentSpec(
                    id="case-other",
                    component="PendingApprovalCard",
                    props={"escalation_id": "c-other"},
                ),
            ],
        )

    spec = compose_ui([], [_case()], "requester", viewer_id="u-newhire-1", runner=runner)
    assert [p.props.get("escalation_id") for p in spec.panels] == ["c-1"]


def test_fallback_when_runner_raises():
    def runner(prompt: str) -> UISpec:
        raise RuntimeError("gemini down")

    spec = compose_ui([_grant()], [_case()], "requester", viewer_id="u-newhire-1", runner=runner)
    names = [p.component for p in spec.panels]
    assert "GrantCard" in names
    assert "PendingApprovalCard" in names
    assert spec.panels[0].id == "grant-g-1"


def test_fallback_approver_layout():
    spec = compose_ui([_grant()], [_case()], "approver", viewer_id="u-manager-1")
    names = [p.component for p in spec.panels]
    assert names[0] == "PendingApprovalCard"
    assert spec.panels[0].id == "case-c-1"
    assert "GrantCard" in names


def test_fallback_auditor_layout():
    spec = compose_ui([_grant()], [_case()], "auditor", viewer_id="u-auditor-1")
    names = [p.component for p in spec.panels]
    assert names[0] == "AuditTimeline"
    assert spec.panels[0].id == "audit-u-auditor-1"
    assert "GrantCard" in names
    assert "PendingApprovalCard" not in names


def test_fallback_emits_watch_card_when_url_present():
    spec = compose_ui(
        [_grant()],
        [],
        "requester",
        viewer_id="u-newhire-1",
        watch_urls={"g-1": "https://watch.example/vnc"},
    )
    watch = [p for p in spec.panels if p.component == "ConsoleWatchCard"]
    assert len(watch) == 1
    assert watch[0].id == "watch-g-1"
    assert watch[0].props["watch_url"] == "https://watch.example/vnc"
    assert watch[0].props["grant_id"] == "g-1"


def test_watch_card_appended_even_when_runner_omits_it():
    def runner(prompt: str) -> UISpec:
        return UISpec(
            requester_id="u-newhire-1",
            panels=[
                UIComponentSpec(id="grant-g-1", component="GrantCard", props={"grant_id": "g-1"}),
            ],
        )

    spec = compose_ui(
        [_grant()],
        [],
        "requester",
        viewer_id="u-newhire-1",
        runner=runner,
        watch_urls={"g-1": "https://watch.example/vnc"},
    )
    assert any(p.id == "watch-g-1" for p in spec.panels)


def test_fallback_skips_inactive_grants_and_nonpending_cases():
    now = datetime.now(timezone.utc)
    revoked = Grant(
        id="g-revoked",
        request_id="r-2",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=now + timedelta(days=14),
        revoked=True,
    )
    expired = Grant(
        id="g-expired",
        request_id="r-3",
        resource_id="bucket-analytics-raw",
        requester_id="u-newhire-1",
        expires_at=now - timedelta(days=1),
    )
    decided = EscalationCase(
        id="c-denied",
        request_id="r-2",
        resource_id="bq-project-x-finance",
        required_approver_ids=["u-manager-1"],
        requester_id="u-newhire-1",
        requested_duration_days=14,
        status="denied",
    )
    spec = compose_ui(
        [revoked, expired],
        [decided],
        "requester",
        viewer_id="u-newhire-1",
    )
    assert spec.panels == []


def test_handle_compose_returns_uispec_dict():
    from modal_app import handle_compose

    out = handle_compose(
        {
            "grants": [_grant().model_dump(mode="json")],
            "cases": [_case().model_dump(mode="json")],
            "role": "requester",
            "viewer_id": "u-newhire-1",
        }
    )
    assert out["requester_id"] == "u-newhire-1"
    names = [p["component"] for p in out["panels"]]
    assert "GrantCard" in names
    assert "PendingApprovalCard" in names
    assert out["panels"][0]["id"] == "grant-g-1"


def test_handle_compose_uses_injected_compose():
    from modal_app import handle_compose

    def compose(grants, cases, role, *, viewer_id):
        return UISpec(
            requester_id=viewer_id,
            panels=[
                UIComponentSpec(
                    id="grant-g-1",
                    component="GrantCard",
                    props={"grant_id": grants[0].id},
                )
            ],
        )

    out = handle_compose(
        {
            "grants": [_grant().model_dump(mode="json")],
            "cases": [],
            "role": "requester",
            "viewer_id": "u-newhire-1",
        },
        compose=compose,
    )
    assert out["panels"][0]["props"]["grant_id"] == "g-1"
