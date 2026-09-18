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
    assert 'name="next"' in resp.text
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
    assert f'href="{prefix}/import-studio"' in resp.text
    loc = client.post(
        "/locale",
        data={"lang": "en"},
        headers={"X-Ingress-Path": prefix},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"].startswith(prefix)


def test_locale_keeps_next_without_referer():
    client = TestClient(app)
    prefix = "/api/hassio_ingress/testtoken"
    loc = client.post(
        "/locale",
        data={"lang": "en", "next": "/import-studio?q=ah"},
        headers={"X-Ingress-Path": prefix},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"] == f"{prefix}/import-studio?q=ah"


def test_locale_rejects_open_redirect_next():
    client = TestClient(app)
    prefix = "/api/hassio_ingress/testtoken"
    loc = client.post(
        "/locale",
        data={"lang": "nl", "next": "https://example.invalid/"},
        headers={"X-Ingress-Path": prefix},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"] == f"{prefix}/"


def test_locale_next_on_laptop_has_no_prefix():
    client = TestClient(app)
    loc = client.post(
        "/locale",
        data={"lang": "en", "next": "/?from_year=2026"},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"] == "/?from_year=2026"


def test_tx_route_still_exists():
    client = TestClient(app)
    resp = client.get("/tx")
    assert resp.status_code in (200, 400, 422, 503)


def test_zoom_hud_is_fixed():
    css = (ROOT / "findash/app/static/css/app.css").read_text()
    assert "position: fixed" in css
    assert ".zoom-hud" in css
    assert "min(68rem" in css
    html = (ROOT / "findash/app/templates/base.html").read_text()
    assert "block float" in html


def test_chart_css_lets_chartjs_size_canvas():
    css = (ROOT / "findash/app/static/css/app.css").read_text()
    assert "contain: inline-size" not in css
    canvas_block = css.split(".chart-frame canvas")[1].split("figcaption")[0]
    assert "!important" not in canvas_block
    assert "position: absolute" not in canvas_block


def test_saving_chart_is_line():
    js = (ROOT / "findash/app/static/js/charts.js").read_text()
    assert 'type: "line"' in js
    assert "htmx:afterSettle" in js
    assert "setTimeout(resizeCharts" in js
    assert "Chart.getChart" in js
    assert 'target.id === "dashboard"' in js
    assert "chart-time" not in js
    studio = (ROOT / "findash/app/templates/studio.html").read_text()
    assert "preset-wrap" in studio
    assert "preset.all" in (ROOT / "findash/app/i18n.py").read_text()


def test_charts_js_prefixes_via_app_url():
    js = (ROOT / "findash/app/static/js/charts.js").read_text()
    assert "function appUrl(" in js
    assert 'appUrl("/tx?"' in js
    assert 'appUrl("/?"' in js
    assert 'const url = "/tx?"' not in js
    assert 'const url = "/?"' not in js


def test_neighbors_query_stays_inside_hx_get():
    html = (ROOT / "findash/app/templates/partials/studio_row.html").read_text()
    assert 'hx-get="{{ base|default(\'\') }}/import-studio/neighbors?src=' in html
    assert 'neighbors"?src=' not in html
