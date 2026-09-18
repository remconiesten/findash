from fastapi.testclient import TestClient

from app.main import app


def test_health_json_shape():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "ok" in body
    if resp.status_code == 200:
        assert body["findash_schema"] in ("ok", "missing")
        assert body.get("qdrant") in ("ok", "disabled", "down", None)
