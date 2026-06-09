"""Unit tests for the FinOps collectors (rightsizing, RI/SP, anomalies).

These don't touch AWS — the per-module `client()` is patched to return a mock
whose API methods yield canned Cost Explorer / Compute Optimizer payloads, so we
verify the response-parsing and Finding construction in isolation.
"""

from unittest import mock

from awsco.collectors import (
    ce_anomalies,
    ce_ri_recommendations,
    ce_savings_plans,
    compute_optimizer_rightsizing,
)
from awsco.models import Category


def _mock_client_returning(method_map):
    """Build a fake boto client whose named methods return canned dicts, and a
    paginator whose paginate() yields the same dict as a single page."""
    fake = mock.MagicMock()
    for name, payload in method_map.items():
        getattr(fake, name).return_value = payload

        def _paginate(_p=payload, **_kw):
            return [_p]

        # get_paginator(name).paginate() -> [payload]
        paginator = mock.MagicMock()
        paginator.paginate.side_effect = _paginate
        fake.get_paginator.return_value = paginator
    return fake


# --- Compute Optimizer rightsizing ----------------------------------------


def test_rightsizing_parses_over_provisioned():
    payload = {
        "instanceRecommendations": [
            {
                "instanceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc",
                "instanceName": "api-worker",
                "currentInstanceType": "m5.2xlarge",
                "finding": "OVER_PROVISIONED",
                "lookBackPeriodInDays": 32,
                "recommendationOptions": [
                    {
                        "instanceType": "m5.large",
                        "performanceRisk": 1.0,
                        "savingsOpportunity": {
                            "savingsOpportunityPercentage": 75.0,
                            "estimatedMonthlySavings": {"currency": "USD", "value": 207.36},
                        },
                    }
                ],
            }
        ]
    }
    fake = _mock_client_returning({"get_ec2_instance_recommendations": payload})
    with mock.patch.object(compute_optimizer_rightsizing, "client", return_value=fake):
        findings = compute_optimizer_rightsizing.collect("us-east-1", "123456789012")

    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.RIGHTSIZING
    assert f.monthly_savings_usd == 207.36
    assert "m5.large" in f.cli_fix_command
    assert f.evidence["recommended_instance_type"] == "m5.large"
    assert not f.fix_destructive


def test_rightsizing_skips_optimized_instances():
    payload = {
        "instanceRecommendations": [
            {
                "instanceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0def",
                "currentInstanceType": "t3.medium",
                "finding": "OPTIMIZED",
                "recommendationOptions": [],
            }
        ]
    }
    fake = _mock_client_returning({"get_ec2_instance_recommendations": payload})
    with mock.patch.object(compute_optimizer_rightsizing, "client", return_value=fake):
        findings = compute_optimizer_rightsizing.collect("us-east-1", "123456789012")
    assert findings == []


# --- Reserved Instance recommendations ------------------------------------


def test_ri_recommendation_parses():
    payload = {
        "Recommendations": [
            {
                "RecommendationSummary": {"TotalEstimatedMonthlySavingsAmount": "318.0"},
                "RecommendationDetails": [
                    {
                        "EstimatedMonthlySavingsAmount": "318.0",
                        "RecommendedNumberOfInstancesToPurchase": "4",
                        "EstimatedBreakEvenInMonths": "7",
                        "UpfrontCost": "0",
                        "InstanceDetails": {
                            "RDSInstanceDetails": {
                                "InstanceType": "db.r5.large",
                                "Region": "us-east-1",
                            }
                        },
                    }
                ],
            }
        ]
    }
    # Only RDS returns something; every other service call returns empty.
    fake = mock.MagicMock()

    def _reco(Service, **_kw):
        if Service == "Amazon Relational Database Service":
            return payload
        return {"Recommendations": []}

    fake.get_reservation_purchase_recommendation.side_effect = _reco
    with mock.patch.object(ce_ri_recommendations, "client", return_value=fake):
        findings = ce_ri_recommendations.collect("us-east-1", "123456789012")

    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.COMMITMENT
    assert f.monthly_savings_usd == 318.0
    assert "db.r5.large" in f.title
    assert ce_ri_recommendations.GLOBAL is True


# --- Savings Plans recommendations ----------------------------------------


def test_savings_plan_parses_summary():
    payload = {
        "SavingsPlansPurchaseRecommendation": {
            "SavingsPlansPurchaseRecommendationSummary": {
                "EstimatedMonthlySavingsAmount": "842.0",
                "HourlyCommitmentToPurchase": "3.20",
                "EstimatedSavingsPercentage": "28",
                "CurrentOnDemandSpend": "3000.0",
                "EstimatedROI": "30",
            }
        }
    }
    fake = mock.MagicMock()

    def _reco(SavingsPlansType, **_kw):
        if SavingsPlansType == "COMPUTE_SP":
            return payload
        return {"SavingsPlansPurchaseRecommendation": {}}

    fake.get_savings_plans_purchase_recommendation.side_effect = _reco
    with mock.patch.object(ce_savings_plans, "client", return_value=fake):
        findings = ce_savings_plans.collect("us-east-1", "123456789012")

    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.COMMITMENT
    assert f.monthly_savings_usd == 842.0
    assert f.evidence["hourly_commitment_usd"] == "3.20"
    assert ce_savings_plans.GLOBAL is True


# --- Cost anomalies --------------------------------------------------------


def test_anomaly_parses_and_has_zero_savings():
    payload = {
        "Anomalies": [
            {
                "AnomalyId": "a-1234",
                "AnomalyStartDate": "2026-05-31T00:00:00Z",
                "AnomalyEndDate": "2026-06-01T00:00:00Z",
                "DimensionValue": "AmazonS3",
                "RootCauses": [{"Service": "AmazonS3"}],
                "Impact": {
                    "TotalImpact": 1240.0,
                    "TotalImpactPercentage": 380.0,
                    "TotalExpectedSpend": 326.0,
                    "TotalActualSpend": 1566.0,
                },
            }
        ]
    }
    fake = _mock_client_returning({"get_anomalies": payload})
    with mock.patch.object(ce_anomalies, "client", return_value=fake):
        findings = ce_anomalies.collect("us-east-1", "123456789012")

    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.ANOMALY
    assert f.monthly_savings_usd == 0.0  # one-off impact, not recurring
    assert f.evidence["impact_usd"] == 1240.0
    assert ce_anomalies.GLOBAL is True


def test_anomaly_ignores_trivial_blips():
    payload = {
        "Anomalies": [
            {
                "AnomalyId": "a-small",
                "DimensionValue": "AmazonEC2",
                "RootCauses": [],
                "Impact": {"TotalImpact": 1.5},  # below MIN_IMPACT_USD
            }
        ]
    }
    fake = _mock_client_returning({"get_anomalies": payload})
    with mock.patch.object(ce_anomalies, "client", return_value=fake):
        findings = ce_anomalies.collect("us-east-1", "123456789012")
    assert findings == []
