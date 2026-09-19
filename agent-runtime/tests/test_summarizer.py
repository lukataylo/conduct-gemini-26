from summarizer import summarize_decision
from shared.schemas import DecisionType, PolicyDecision, Resource, ResourceType, SensitivityTier


def test_summarize_uses_runner_not_raw_requester_text(requester):
    decision = PolicyDecision(
        request_id="r-1",
        resource_id="bq-project-x-finance",
        decision=DecisionType.ESCALATE,
        reason="Cross-team request (data-platform -> finance) — requires 1 approval(s)",
        required_approver_ids=["u-finance-owner-1", "u-manager-1"],
    )
    resource = Resource(
        id="bq-project-x-finance",
        name="project-x-finance",
        type=ResourceType.BIGQUERY_DATASET,
        owning_team="finance",
        sensitivity=SensitivityTier.RESTRICTED,
        project="atlas-migration",
    )

    def runner(prompt: str) -> str:
        assert "I need" not in prompt  # never the requester's raw pitch
        assert "Cross-team request" in prompt
        assert "project-x-finance" in prompt
        return "Alex (data-platform) needs the finance dataset; policy escalated because it is cross-team."

    text = summarize_decision(decision, resource, requester, runner=runner)
    assert "cross-team" in text.lower()


def test_summarize_fallback_is_reason_string(requester):
    decision = PolicyDecision(
        request_id="r-1",
        resource_id="bucket-analytics-raw",
        decision=DecisionType.AUTO_GRANT,
        reason="internal tier, 14d within 30d limit, same-team requester",
    )
    resource = Resource(
        id="bucket-analytics-raw",
        name="analytics-raw",
        type=ResourceType.GCS_BUCKET,
        owning_team="data-platform",
        sensitivity=SensitivityTier.INTERNAL,
        project="atlas-migration",
    )
    assert summarize_decision(decision, resource, requester, runner=lambda p: (_ for _ in ()).throw(RuntimeError("boom"))) == decision.reason
