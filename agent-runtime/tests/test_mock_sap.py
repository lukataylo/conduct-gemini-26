import inspect
from pathlib import Path
from urllib.request import urlopen

HTML = Path(__file__).resolve().parents[1] / "mock_sap" / "index.html"


def test_sap_console_has_fiori_chrome():
    text = HTML.read_text()
    for label in (
        "SAP S/4HANA Cloud",
        "Helios Manufacturing",
        "1000 London",
        "2000",
        "Frankfurt",
        "Authorization",
        "Customer Master",
        "Billing Documents",
        "Sales Orders",
        "Maintain Business Users",
        "Export Customer List",
        "Employee Payroll",
        "Northwind Trading",
        "Contoso Retail",
        "Litware GmbH",
        "Adventure Works",
        "Fabrikam Exports",
        "Thames Precision Ltd",
        "Müller Industriebedarf",
        "Nordic Bearings AB",
        "Amsterdam Port Supplies",
        "1710001",
        "1710002",
        "1710044",
        "1710108",
        "1710200",
        "90001234",
        "4500008123",
        "#0070F2",
        "B_BUPA_GRP",
        "activity 16 Export",
        "No business role assigned",
    ):
        assert label in text
    for gcp in ("Google Cloud", "Cloud Storage", "BigQuery", "Cloud SQL"):
        assert gcp not in text


def test_sap_console_has_dom_contracts():
    text = HTML.read_text()
    assert 'id="active-grants"' in text
    assert "data-resource" in text
    assert "data-principal" in text
    assert 'id="sap-auth-error"' in text
    assert 'id="auth-strip"' in text
    assert 'data-bp="1710001"' in text
    assert "data-tile" in text
    assert 'data-nav="users"' in text
    assert 'data-nav="bp"' in text
    assert 'data-nav="billing"' in text
    assert 'data-nav="sales"' in text
    assert 'data-nav="export"' in text
    assert 'id="principal"' in text
    assert 'id="company-code"' in text
    assert 'id="customer-id"' in text
    assert 'id="valid-to"' in text
    assert 'aria-label="Save role"' in text
    assert 'aria-label="Confirm revoke"' in text
    assert 'id="role"' in text


def test_sap_auth_error_toggles_visible_class():
    text = HTML.read_text()
    assert 'id="sap-auth-error"' in text
    assert 'classList.add("visible")' in text
    assert 'classList.remove("visible")' in text


def test_sap_console_hash_routes():
    text = HTML.read_text()
    for route in (
        "#launchpad",
        "#users",
        "#bp",
        "#bp/1710001",
        "#billing",
        "#sales",
        "#export",
    ):
        assert route in text
    assert 'data-view="payroll"' not in text
    assert 'data-tile="payroll"' in text
    assert "payroll" in text
    assert 'app === "payroll"' in text or 'hash === "payroll"' in text or 'parts[0] === "payroll"' in text


def test_sap_console_has_full_helios_catalog():
    text = HTML.read_text()
    assert "32 Business Partners" in text
    assert "28 customer invoices" in text
    assert "24 open / delivered orders" in text
    assert text.count('id: "171') == 32
    assert text.count('id: "9000') == 28
    assert text.count('id: "4500') == 24
    assert "Priya Nair" in text
    assert "GB 239 1844 01" in text


def test_sap_console_hydrates_from_sap_state():
    text = HTML.read_text()
    assert "/sap/state" in text
    assert "SAP_BACKEND" in text
    assert 'params.get("backend")' in text
    start = text.index("function hydrateFromBackend")
    end = text.index("function applyHash", start)
    body = text[start:end]
    assert "applyHash()" in body
    assert body.index("forEach(renderBinding)") < body.index("applyHash()")


def test_serve_in_thread_defaults_and_serves_index():
    from mock_sap.server import serve_in_thread

    sig = inspect.signature(serve_in_thread)
    assert sig.parameters["host"].default == "127.0.0.1"
    assert sig.parameters["port"].default == 8766

    server = serve_in_thread(host="127.0.0.1", port=0)
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/") as resp:
            body = resp.read().decode()
        assert resp.status == 200
        assert "SAP S/4HANA Cloud" in body
        assert "Helios Manufacturing" in body
        assert 'id="active-grants"' in body
        assert 'id="sap-auth-error"' in body
        assert "Google Cloud" not in body
    finally:
        server.shutdown()
