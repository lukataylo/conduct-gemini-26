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


def test_duration_yearless_no_strptime_warning():
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        duration_days("done by Nov 15", None, today=date(2026, 9, 19))
    assert not any("strptime" in str(w.message).lower() for w in caught)


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


from gemini_parser import ParseFields, parse_request


def test_parse_request_uses_runner_and_drops_unknown(requester):
    def runner(prompt: str) -> ParseFields:
        assert "bucket-analytics-raw" in prompt
        assert "I need access" in prompt
        return ParseFields(
            project="atlas-migration",
            resource_ids=["bucket-analytics-raw", "totally-fake"],
            requested_duration_days=14,
        )

    req = parse_request(
        "I need access to analytics-raw for Project Atlas",
        requester,
        ["bucket-analytics-raw", "bq-project-x-finance"],
        runner=runner,
    )
    assert req.resource_ids == ["bucket-analytics-raw"]
    assert req.project == "atlas-migration"
    assert req.requested_duration_days == 14
    assert req.requester.id == "u-newhire-1"


def test_parse_request_empty_ids_when_nothing_matches(requester):
    def runner(prompt: str) -> ParseFields:
        return ParseFields(project="x", resource_ids=["nope"], requested_duration_days=7)

    req = parse_request("please give me prod", requester, ["bucket-analytics-raw"], runner=runner)
    assert req.resource_ids == []
