from datetime import date

from gemini_parser import constrain_resource_ids, duration_days, _build_request
from shared.schemas import Requester

ALEX = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="SE",
    team="data-platform",
    manager_id="u-manager-1",
)
KNOWN = ["bucket-analytics-raw", "bq-project-x-finance", "sql-prod-primary"]


def test_constrain_drops_unknown_preserves_order():
    assert constrain_resource_ids(
        ["bq-project-x-finance", "not-a-thing", "bucket-analytics-raw"],
        KNOWN,
    ) == ["bq-project-x-finance", "bucket-analytics-raw"]


def test_constrain_dedupes():
    assert constrain_resource_ids(["bucket-analytics-raw", "bucket-analytics-raw"], KNOWN) == [
        "bucket-analytics-raw"
    ]


def test_duration_defaults_to_14():
    assert duration_days("I need the analytics-raw bucket", None) == 14


def test_duration_uses_parsed_value():
    assert duration_days("need access", 30) == 30


def test_duration_from_done_by_date():
    assert duration_days(
        "done by Nov 15",
        None,
        today=date(2026, 9, 19),
    ) == (date(2026, 11, 15) - date(2026, 9, 19)).days


def test_duration_minimum_one_day():
    assert duration_days("done by Sep 1", None, today=date(2026, 9, 19)) == 1


def test_build_request_keeps_raw_text(requester):
    req = _build_request(
        raw_text="I need analytics-raw for Project Atlas",
        requester=requester,
        project="atlas-migration",
        resource_ids=["bucket-analytics-raw"],
        requested_duration_days=14,
    )
    assert req.raw_text == "I need analytics-raw for Project Atlas"
    assert req.task_description == req.raw_text
    assert req.resource_ids == ["bucket-analytics-raw"]
