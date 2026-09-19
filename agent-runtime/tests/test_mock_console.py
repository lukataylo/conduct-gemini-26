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
