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


def test_validate_rejects_malformed_account_id():
    AppState.demo_mode = True
    client = TestClient(create_app())
    resp = client.post("/aws/validate", json={"expected_account_id": "12345"})
    assert resp.status_code == 422


def test_unknown_host_header_is_rejected():
    """DNS-rebinding guard: only loopback Host headers are served."""
    AppState.demo_mode = True
    client = TestClient(create_app())
    assert client.get("/healthz", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/healthz", headers={"host": "localhost:3000"}).status_code == 200


def test_credential_warnings_flag_root_and_long_lived_keys():
    from awsco.server import credential_warnings

    root = credential_warnings("arn:aws:iam::123456789012:root", "AKIAEXAMPLE")
    assert len(root) == 2 and "ROOT" in root[0]
    assert credential_warnings("arn:aws:sts::1:assumed-role/r/s", "ASIAEXAMPLE") == []


def test_demo_lists_every_commercial_region():
    from awsco.regions import commercial_regions

    AppState.demo_mode = True
    client = TestClient(create_app())
    names = [r["name"] for r in client.get("/aws/regions").json()["regions"]]
    assert names == commercial_regions()
    assert len(names) >= 34 and {"mx-central-1", "ap-southeast-7", "ca-west-1"} <= set(names)
    assert len(client.post("/scan", json={}).json()["regions_scanned"]) == len(names)
