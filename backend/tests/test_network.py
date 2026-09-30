"""Network checks: idle endpoints / TGW / VPN, abandoned VPCs, unused SGs,
the VPC roll-up, and the configurable lookback. No AWS calls."""

from unittest import mock

from awsco import aws, scanner
from awsco.collectors import sg_unused, vpc_abandoned, vpc_endpoint_idle, vpn_idle
from awsco.demo.fixtures import build_demo_scan
from awsco.models import Category


def _cw(datapoints=None, metrics=None):
    cw = mock.MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": datapoints or []}
    cw.get_paginator.return_value.paginate.return_value = [{"Metrics": metrics or []}]
    return cw


def _clients(mapping):
    return lambda service, region, profile=None: mapping[service]


def test_idle_interface_endpoint_is_priced_per_az():
    ec2 = mock.MagicMock()
    ec2.get_paginator.return_value.paginate.return_value = [{"VpcEndpoints": [
        {"VpcEndpointId": "vpce-1", "State": "available", "VpcId": "vpc-1",
         "ServiceName": "com.amazonaws.us-east-1.ecr.dkr", "SubnetIds": ["a", "b", "c"]},
        {"VpcEndpointId": "vpce-2", "State": "available", "RequesterManaged": True},
    ]}]
    dims = [{"Name": "VPC Endpoint Id", "Value": "vpce-1"}]
    cw = _cw(datapoints=[{"Sum": 0.0}], metrics=[{"Dimensions": dims}])
    with mock.patch.object(vpc_endpoint_idle, "client", _clients({"ec2": ec2, "cloudwatch": cw})):
        found = vpc_endpoint_idle.collect("us-east-1", "111122223333")

    assert [f.resource_id for f in found] == ["vpce-1"]  # AWS-managed one skipped
    assert found[0].monthly_savings_usd == 21.6


def test_busy_vpn_is_not_flagged():
    ec2 = mock.MagicMock()
    ec2.describe_vpn_connections.return_value = {"VpnConnections": [{"VpnConnectionId": "vpn-1"}]}
    cw = _cw(datapoints=[{"Sum": 5e9}])
    with mock.patch.object(vpn_idle, "client", _clients({"ec2": ec2, "cloudwatch": cw})):
        assert vpn_idle.collect("us-east-1", "1") == []


def _vpc_ec2(enis):
    ec2 = mock.MagicMock()

    def paginator(name):
        pages = {
            "describe_vpcs": [{"Vpcs": [{"VpcId": "vpc-1", "IsDefault": False, "OwnerId": "1"}]}],
            "describe_network_interfaces": [{"NetworkInterfaces": enis}],
        }[name]
        p = mock.MagicMock()
        p.paginate.return_value = pages
        return p

    ec2.get_paginator.side_effect = paginator
    ec2.describe_nat_gateways.return_value = {"NatGateways": [{"NatGatewayId": "nat-1"}]}
    ec2.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
    ec2.describe_transit_gateway_vpc_attachments.return_value = {"TransitGatewayVpcAttachments": []}
    ec2.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": []}
    ec2.describe_flow_logs.return_value = {"FlowLogs": []}
    return ec2


def _run_vpc(enis, cloudtrail_events=()):
    elbv2 = mock.MagicMock()
    elbv2.get_paginator.return_value.paginate.return_value = [{"LoadBalancers": []}]
    ct = mock.MagicMock()
    ct.lookup_events.return_value = {"Events": list(cloudtrail_events)}
    clients = {"ec2": _vpc_ec2(enis), "elbv2": elbv2, "cloudwatch": _cw(), "cloudtrail": ct}
    with mock.patch.object(vpc_abandoned, "client", _clients(clients)):
        return vpc_abandoned.collect("us-east-1", "1")


NAT_ENI = {"Status": "in-use", "InterfaceType": "nat_gateway",
           "Association": {"PublicIp": "1.2.3.4"}}


def test_vpc_with_only_idle_infrastructure_is_abandoned():
    found = _run_vpc([NAT_ENI])
    assert len(found) == 1
    f = found[0]
    assert f.resource_id == "vpc-1" and f.fix_destructive
    assert f.monthly_savings_usd == 36.0  # NAT $32.40 + its public IPv4 $3.60
    assert set(f.evidence["member_resource_ids"]) >= {"nat-1", "1.2.3.4"}
    assert f.cli_fix_command.startswith("aws ")


def test_vpc_with_a_running_workload_is_not_flagged():
    instance_eni = {"Status": "in-use", "InterfaceType": "interface",
                    "Attachment": {"InstanceId": "i-1"}, "Description": ""}
    assert _run_vpc([NAT_ENI, instance_eni]) == []


def test_recently_changed_vpc_is_not_flagged():
    from datetime import datetime, timezone

    assert _run_vpc([NAT_ENI], [{"EventTime": datetime.now(timezone.utc)}]) == []


def test_unused_sg_is_hygiene_and_flags_open_ports():
    ec2 = mock.MagicMock()
    groups = [
        {"GroupId": "sg-used", "GroupName": "web"},
        {"GroupId": "sg-ref", "GroupName": "db"},
        {"GroupId": "sg-default", "GroupName": "default"},
        {"GroupId": "sg-old", "GroupName": "old-bastion", "IpPermissions": [
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
             "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        ]},
    ]
    groups[0]["IpPermissions"] = [{"UserIdGroupPairs": [{"GroupId": "sg-ref"}]}]

    def paginator(name):
        p = mock.MagicMock()
        p.paginate.return_value = {
            "describe_security_groups": [{"SecurityGroups": groups}],
            "describe_network_interfaces": [{"NetworkInterfaces": [
                {"Groups": [{"GroupId": "sg-used"}]}]}],
        }[name]
        return p

    ec2.get_paginator.side_effect = paginator
    with mock.patch.object(sg_unused, "client", return_value=ec2):
        found = sg_unused.collect("us-east-1", "1")

    assert [f.resource_id for f in found] == ["sg-old"]
    assert found[0].category == Category.HYGIENE and found[0].monthly_savings_usd == 0
    assert found[0].evidence["open_to_world"] == ["tcp/22"]


def test_vpc_members_are_rolled_into_the_vpc_total():
    scan = build_demo_scan()
    vpc = next(f for f in scan.findings if f.check_id == "vpc.abandoned")
    rolled = {f.resource_id for f in scan.findings if f.superseded_by == vpc.id}
    assert {"nat-0a1b2c3d4e5f6", "staging-old-alb", "vpce-0staging01"} <= rolled


def test_lookback_is_clamped_and_reset():
    token = aws.set_lookback_days(365)
    assert aws.lookback_days() == aws.MAX_LOOKBACK_DAYS
    aws.reset_lookback_days(token)
    assert aws.lookback_days() == aws.DEFAULT_LOOKBACK_DAYS


def test_scan_records_lookback_on_findings():
    with mock.patch.object(scanner, "caller_identity", return_value={"account_id": "1"}), \
         mock.patch.object(scanner, "ALL_COLLECTORS", []), \
         mock.patch.object(scanner, "spend_summary", return_value=None):
        result = scanner.run_scan(regions=["us-east-1"], lookback_days=30)
    assert result.lookback_days == 30


# Review fix #7: a single ALB request means the VPC is in use.
def test_vpc_with_one_alb_request_is_not_abandoned():
    alb = {"LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/api/abc",
           "LoadBalancerName": "api", "Type": "application", "VpcId": "vpc-1"}
    elbv2 = mock.MagicMock()
    elbv2.get_paginator.return_value.paginate.return_value = [{"LoadBalancers": [alb]}]
    cw = mock.MagicMock()

    def stats(**kw):
        return {"Datapoints": [{"Sum": 1.0}] if kw["MetricName"] == "RequestCount" else []}

    cw.get_metric_statistics.side_effect = stats
    cw.get_paginator.return_value.paginate.return_value = [{"Metrics": []}]
    ct = mock.MagicMock()
    ct.lookup_events.return_value = {"Events": []}
    clients = {"ec2": _vpc_ec2([NAT_ENI]), "elbv2": elbv2, "cloudwatch": cw, "cloudtrail": ct}
    with mock.patch.object(vpc_abandoned, "client", _clients(clients)):
        assert vpc_abandoned.collect("us-east-1", "1") == []
