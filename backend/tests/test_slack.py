"""Owner resolution + the Slack confirmation flow. No AWS or Slack calls."""

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from awsco import ownership, slack
from awsco.demo.fixtures import build_demo_scan
from awsco.server import AppState, create_app


# --- ownership -------------------------------------------------------------------


def test_owner_tag_wins_and_extracts_email():
    o = ownership.owner_from_tags({"Name": "x", "Owner": "Priya <priya@acme.io>"})
    assert o == {"source": "tag", "name": "Priya <priya@acme.io>",
                 "email": "priya@acme.io", "tag_key": "owner"}
    assert ownership.owner_from_tags({"Name": "x"}) is None


@pytest.mark.parametrize("ident,name,email", [
    ({"type": "AssumedRole",
      "arn": "arn:aws:sts::1:assumed-role/AWSReservedSSO_Admin_ab/venka@acme.io"},
     "venka@acme.io", "venka@acme.io"),
    ({"type": "IAMUser", "arn": "arn:aws:iam::1:user/deploy", "userName": "deploy"},
     "deploy", None),
    ({"type": "AssumedRole", "arn": "arn:aws:sts::1:assumed-role/ci-deployer/gh-run-42"},
     "gh-run-42 (role ci-deployer)", None),
    ({"type": "Root", "arn": "arn:aws:iam::1:root"}, "root account", None),
])
def test_identity_from_cloudtrail_event(ident, name, email):
    who = ownership.identity_from_event({"userIdentity": ident})
    assert who["name"] == name and who["email"] == email


def test_cloudtrail_prefers_the_creation_event():
    def event(name, arn):
        return {"EventName": name, "EventTime": "2026-01-01",
                "CloudTrailEvent": json.dumps({"userIdentity": {"type": "IAMUser", "arn": arn}})}

    ct = mock.MagicMock()
    ct.get_paginator.return_value.paginate.return_value = [{"Events": [
        event("ModifyVolume", "arn:aws:iam::1:user/bob"),       # newest
        event("DescribeVolumes", "arn:aws:iam::1:user/carol"),  # read: ignored
        event("CreateVolume", "arn:aws:iam::1:user/alice"),     # oldest = creator
    ]}]
    with mock.patch.object(ownership, "client", return_value=ct):
        o = ownership.owner_from_cloudtrail("vol-1", "us-east-1")
    assert o["name"] == "alice" and o["relationship"] == "created"


# --- deciding the answer -------------------------------------------------------


def test_only_the_owner_counts_and_keep_wins():
    reactions = [{"name": "wastebasket", "users": ["U_OWNER", "U_OTHER"]},
                 {"name": "white_check_mark", "users": ["U_OTHER"]}]
    assert slack.decide(reactions, "U_OWNER", "U_BOT") == ("delete_ok", "U_OWNER")
    both = reactions + [{"name": "white_check_mark", "users": ["U_OWNER"]}]
    assert slack.decide(both[:1] + both[2:], "U_OWNER", "U_BOT") == ("keep", "U_OWNER")
    # unknown owner: anyone but the bot
    assert slack.decide([{"name": "wastebasket", "users": ["U_BOT", "U_X"]}], None, "U_BOT") \
        == ("delete_ok", "U_X")
    assert slack.decide([], "U_OWNER", "U_BOT") == ("pending", None)


def test_message_mentions_owner_and_explains_the_ask():
    f = next(x for x in build_demo_scan().findings if x.resource_id == "i-0idleanalytics01")
    msg = slack.build_message(f, "U123")
    blob = json.dumps(msg)
    assert "<@U123>" in msg["text"]
    assert "RunInstances" in blob and ":white_check_mark:" in blob and ":wastebasket:" in blob
    assert "Nothing is deleted automatically" in blob


# --- API ---------------------------------------------------------------------------


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    import awsco.storage as storage

    db = tmp_path / "t.sqlite"
    for fn in ("save_scan", "latest_scan", "save_confirmation", "list_confirmations"):
        orig = getattr(storage, fn)
        monkeypatch.setattr(f"awsco.server.{fn}",
                            lambda *a, _o=orig, **k: _o(*a, db_path=db, **k))
    AppState.demo_mode = True
    return TestClient(create_app())


def test_demo_ask_and_sync_round_trip(demo_client):
    scan = demo_client.post("/scan", json={}).json()
    fid = next(f["id"] for f in scan["findings"] if f["resource_id"] == "i-0idleanalytics01")

    asked = demo_client.post(f"/findings/{fid}/ask-owner", json={}).json()
    assert asked["simulated"] and not asked["sent"]
    assert demo_client.get("/confirmations").json()["confirmations"][0]["status"] == "pending"

    synced = demo_client.post("/confirmations/sync").json()
    assert synced["updated"] == 1
    assert synced["confirmations"][0]["status"] == "delete_ok"


def test_unknown_finding_is_404(demo_client):
    demo_client.post("/scan", json={})
    assert demo_client.post("/findings/nope/ask-owner", json={}).status_code == 404


def test_real_send_posts_to_channel_with_mention(monkeypatch):
    monkeypatch.setenv("AWSCO_SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("AWSCO_SLACK_CHANNEL", "C999")
    calls = []

    def fake_call(method, **params):
        calls.append((method, params))
        if method == "users.lookupByEmail":
            return {"user": {"id": "U777"}}
        return {"channel": "C999", "ts": "1.2"}

    monkeypatch.setattr(slack, "call", fake_call)
    f = next(x for x in build_demo_scan().findings if x.resource_id == "prod-leftover-db")
    out = slack.ask_owner(f)
    assert out["sent"] and out["owner_slack_id"] == "U777"
    method, params = calls[-1]
    assert method == "chat.postMessage" and params["channel"] == "C999"
    assert "<@U777>" in params["text"]
