from fastapi.testclient import TestClient

from awsco.server import AppState, create_app


def test_healthz():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_demo_scan_endpoint():
    AppState.demo_mode = True
    client = TestClient(create_app())
    resp = client.post("/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_demo"] is True
    assert len(body["findings"]) > 0
    AppState.demo_mode = False
