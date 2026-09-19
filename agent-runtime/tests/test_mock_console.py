from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "mock_console" / "index.html"


def test_console_has_required_labels():
    text = HTML.read_text()
    for label in ("Grant access", "Principal", "Expires", "Confirm", "Active grants"):
        assert label in text
    for name in ("analytics-raw", "project-x-finance", "prod-primary"):
        assert name in text
    assert 'id="active-grants"' in text
    assert "data-resource" in text


def test_console_has_gcp_chrome_and_product_tabs():
    text = HTML.read_text()
    for label in (
        "Google Cloud",
        "Cloud Storage",
        "BigQuery",
            "IAM &amp; Admin",
        "Buckets",
        "Objects",
        "Configuration",
        "Permissions",
        "Protection",
        "Lifecycle",
        "Replication",
        "Observability",
        "New principals",
        "Select a role",
        "Sharing",
        "Cloud SQL Instances",
        "Connections",
        "Users",
        "Databases",
        "Backups",
        "Service accounts",
    ):
        assert label in text
    assert 'role="tab"' in text
    assert 'data-open-resource="bucket-analytics-raw"' in text
    assert 'data-open-resource="bq-project-x-finance"' in text
    assert 'data-open-resource="sql-prod-primary"' in text


def test_console_has_revoke_and_hash_hooks():
    text = HTML.read_text()
    assert 'data-action="revoke"' in text
    assert 'aria-label="Confirm revoke"' in text
    assert 'data-hash-example="#storage/bucket-analytics-raw/permissions"' in text
    assert "location.hash" in text
    assert "Remove" in text


def test_console_has_object_preview_and_query():
    text = HTML.read_text()
    assert 'data-object="events/2026-09-18.parquet"' in text
    assert 'id="object-preview"' in text
    assert 'id="query-editor"' in text
    assert 'id="query-run"' in text
    assert 'id="query-results"' in text
    assert 'data-dataset="bq-project-x-finance"' in text
