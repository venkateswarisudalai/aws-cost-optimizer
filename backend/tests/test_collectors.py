"""Structural checks over the collector registry.

These don't hit AWS — they guarantee every collector is wired up consistently
and that the demo fixtures only reference check_ids that real collectors emit.
"""

import inspect

from awsco.collectors import ALL_COLLECTORS
from awsco.demo.fixtures import build_demo_scan


def test_every_collector_has_check_id_and_collect():
    for c in ALL_COLLECTORS:
        assert isinstance(getattr(c, "CHECK_ID", None), str) and c.CHECK_ID
        assert callable(getattr(c, "collect", None))


def test_collect_signature_is_uniform():
    # collect(region, account_id, profile=None)
    for c in ALL_COLLECTORS:
        params = list(inspect.signature(c.collect).parameters)
        assert params[:3] == ["region", "account_id", "profile"], c.CHECK_ID


def test_check_ids_are_unique():
    ids = [c.CHECK_ID for c in ALL_COLLECTORS]
    assert len(ids) == len(set(ids)), f"duplicate CHECK_IDs: {ids}"


def test_demo_check_ids_are_all_registered():
    registered = {c.CHECK_ID for c in ALL_COLLECTORS}
    demo_ids = {f.check_id for f in build_demo_scan().findings}
    unknown = demo_ids - registered
    assert not unknown, f"demo references unregistered check_ids: {unknown}"


def test_new_collectors_are_registered():
    registered = {c.CHECK_ID for c in ALL_COLLECTORS}
    for expected in {
        "ec2.idle",
        "rds.snapshot-old",
        "dynamodb.idle-provisioned",
        "elasticache.idle",
        "redshift.idle",
    }:
        assert expected in registered
