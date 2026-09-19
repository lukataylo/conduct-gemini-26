from datetime import date

from gemini_parser import constrain_resource_ids, duration_days, hint_resource_ids, _build_request
from shared.schemas import Requester

ALEX = Requester(
    id="u-newhire-1",
    name="Alex Chen",
    role="SE",
    team="data-platform",
    manager_id="u-manager-1",
)
KNOWN = ["bucket-analytics-raw", "bq-project-x-finance", "sql-prod-primary"]
SAP_KNOWN = KNOWN + [
    "sap-bp-display",
    "sap-billing-display",
    "sap-sales-order-display",
    "sap-customer-directory",
    "sap-hr-payroll",
]
ATLAS_TEXT = "I need access to analytics-raw for Project Atlas"


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


def test_hint_northwind_and_customer_master_map_to_bp():
    for text in (
        "display Northwind Trading 1710001 in Customer Master for INC-8841",
        "business partner 1710001",
        "northwind",
        "customer master",
    ):
        assert hint_resource_ids(text, SAP_KNOWN) == ["sap-bp-display"]


def test_hint_billing_and_sales_order():
    assert hint_resource_ids("need the billing doc", SAP_KNOWN) == ["sap-billing-display"]
    assert hint_resource_ids("need the sales order", SAP_KNOWN) == ["sap-sales-order-display"]


def test_hint_export_needles_map_to_directory():
    for text in (
        "export all customers",
        "export customer list",
        "full customer directory",
        "all customers",
    ):
        assert hint_resource_ids(text, SAP_KNOWN) == ["sap-customer-directory"]


def test_hint_payroll_maps_to_hr():
    assert hint_resource_ids("need payroll access", SAP_KNOWN) == ["sap-hr-payroll"]


def test_hint_full_customer_file_is_not_export():
    assert "sap-customer-directory" not in hint_resource_ids(
        "I do not need the full customer file", SAP_KNOWN
    )
    assert hint_resource_ids(
        "I need display on Northwind Trading customer 1710001 in SAP Customer Master "
        "to answer INC-8841. I do not need the full customer file.",
        SAP_KNOWN,
    ) == ["sap-bp-display"]


def test_hint_skips_ids_not_in_known():
    assert hint_resource_ids("payroll and northwind", KNOWN) == []


def test_hint_atlas_text_maps_to_no_sap_ids():
    assert hint_resource_ids(ATLAS_TEXT, SAP_KNOWN) == []


def test_parse_request_merges_hints_after_constrain(requester):
    def runner(prompt: str) -> ParseFields:
        return ParseFields(
            project="atlas-migration",
            resource_ids=["totally-fake"],
            requested_duration_days=3,
        )

    req = parse_request(
        "display Northwind Trading 1710001 in Customer Master for INC-8841",
        requester,
        SAP_KNOWN,
        runner=runner,
    )
    assert req.resource_ids == ["sap-bp-display"]


def test_parse_request_atlas_text_stays_gcp_only(requester):
    def runner(prompt: str) -> ParseFields:
        return ParseFields(
            project="atlas-migration",
            resource_ids=["bucket-analytics-raw"],
            requested_duration_days=14,
        )

    req = parse_request(ATLAS_TEXT, requester, SAP_KNOWN, runner=runner)
    assert req.resource_ids == ["bucket-analytics-raw"]
