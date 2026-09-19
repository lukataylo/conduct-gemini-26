"""
The Friday Finance Freeze, end to end: every success criterion in
usecase-demo/PolicyBasedUserCaseDemo.md must hold on the real engine's output, and the
payload the console's Policy tab renders must be complete and deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend-api"))
sys.path.append(str(ROOT))

import policy_demo  # noqa: E402

FRONTEND_FIELDS = {"requester", "resources", "ticket", "decisions", "compliance", "context_snapshot"}


def test_every_success_criterion_passes():
    story = policy_demo.build_final_story()
    failed = [c for c in story["checks"] if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed)
    assert story["all_pass"] is True
    assert len(story["checks"]) == 9


def test_eight_scenarios_in_doc_order_with_display_fields():
    story = policy_demo.build_final_story()
    titles = [s["title"] for s in story["scenarios"]]
    assert titles == [
        "Safe Internal Access",
        "PowerBI View vs Export",
        "Earnings Quiet Period",
        "Warehouse Geofence Deny",
        "Support Impersonation Mismatch",
        "Secret Harvesting Alarm",
        "Evidence-Based Escalation Card",
        "Reaper: Jira ATLAS-101 Done → Auto-Revoke",
    ]
    for s in story["scenarios"]:
        assert s["beat"] == titles.index(s["title"]) + 1
        assert s["requester"]["name"] and s["resources"] and s["ticket"]["ticket_id"]
        assert "compliance" in s and "context" in s
        if s["kind"] == "request":
            assert FRONTEND_FIELDS <= set(s)
            for d in s["decisions"]:
                assert d["reason"], "every decision carries its exact policy reason"
        assert not any(k.startswith("_") for k in s), "no engine objects leak into the payload"


def test_reaper_shows_grant_then_reclaims_it_on_done():
    reaper = next(s for s in policy_demo.build_final_story()["scenarios"] if s["kind"] == "reaper")
    before, after = reaper["before"], reaper["after"]
    assert before["jira"]["status"] == "IN_PROGRESS" and after["jira"]["status"] == "DONE"
    assert before["toast"] is None and before["revocations"] == []
    assert after["toast"] == "Access reclaimed: Jira ATLAS-101 is complete."
    reclaimed = {g["id"]: g["reclaimed"] for g in after["grants"]}
    assert reclaimed == {"grant-finance-atlas-101": True, "grant-secret-1": False}, "only the ATLAS-101 grant is reclaimed"
    assert "ATLAS-101" in after["revocations"][0]["reason"]


def test_story_is_deterministic_and_json_serialisable():
    a = json.dumps(policy_demo.build_final_story(), sort_keys=True)
    b = json.dumps(policy_demo.build_final_story(), sort_keys=True)
    assert a == b
