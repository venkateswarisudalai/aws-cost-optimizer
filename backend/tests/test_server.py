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


def test_validate_demo_mode():
    AppState.demo_mode = True
    client = TestClient(create_app())
    resp = client.post("/aws/validate", json={"profile": "demo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "123456789012"
    assert len(body["regions"]) > 0
    AppState.demo_mode = False


def test_validate_rejects_short_access_key():
    AppState.demo_mode = False
    client = TestClient(create_app())
    resp = client.post(
        "/aws/validate",
        json={"credentials": {"access_key_id": "too-short", "secret_access_key": "x"}},
    )
    assert resp.status_code == 422  # pydantic min_length on access_key_id
