from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_static_and_nav_unprefixed_without_ingress():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code in (200, 503)
    assert '<base id="app-base" href="/">' in resp.text
    assert 'href="static/css/app.css' in resp.text
    assert 'href="/static/css/app.css' not in resp.text
    assert 'hx-get="."' in resp.text
    css = client.get("/static/css/app.css")
    assert css.status_code == 200
    assert b'url("/static/' not in css.content
    assert b'url("../fonts/' in css.content


def test_ingress_prefix_on_html_and_redirect():
    client = TestClient(app)
    prefix = "/api/hassio_ingress/testtoken"
    resp = client.get("/", headers={"X-Ingress-Path": prefix})
    assert resp.status_code in (200, 503)
    assert f'<base id="app-base" href="{prefix}/">' in resp.text
    assert 'href="static/css/app.css' in resp.text
    assert 'href="import-studio"' in resp.text
    loc = client.post(
        "/locale",
        data={"lang": "en"},
        headers={"X-Ingress-Path": prefix},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"].startswith(prefix)


def test_tx_route_still_exists():
    client = TestClient(app)
    resp = client.get("/tx")
    assert resp.status_code in (200, 400, 422, 503)


def test_charts_js_prefixes_via_app_url():
    js = (ROOT / "findash/app/static/js/charts.js").read_text()
    assert "function appUrl(" in js
    assert 'appUrl("/tx?"' in js
    assert 'appUrl("/?"' in js
    assert 'const url = "/tx?"' not in js
    assert 'const url = "/?"' not in js


def test_neighbors_query_stays_inside_hx_get():
    html = (ROOT / "findash/app/templates/partials/studio_row.html").read_text()
    assert 'hx-get="import-studio/neighbors?src=' in html
    assert 'neighbors"?src=' not in html
