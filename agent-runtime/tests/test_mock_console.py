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
