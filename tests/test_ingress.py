from fastapi.testclient import TestClient

from app.main import app


def test_static_and_nav_unprefixed_without_ingress():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code in (200, 503)
    assert 'href="/static/css/app.css' in resp.text
    assert 'hx-get="/"' in resp.text or 'href="/"' in resp.text


def test_ingress_prefix_on_html_and_redirect():
    client = TestClient(app)
    prefix = "/api/hassio_ingress/testtoken"
    resp = client.get("/", headers={"X-Ingress-Path": prefix})
    assert resp.status_code in (200, 503)
    assert f'href="{prefix}/static/css/app.css' in resp.text
    assert f'href="{prefix}/import-studio"' in resp.text
    loc = client.post(
        "/locale",
        data={"lang": "en"},
        headers={"X-Ingress-Path": prefix},
        follow_redirects=False,
    )
    assert loc.status_code == 303
    assert loc.headers["location"].startswith(prefix)
