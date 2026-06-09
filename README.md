# aws-cost-optimizer

> Find wasted AWS spend in 60 seconds, without giving a SaaS vendor your credentials.

`aws-cost-optimizer` scans your AWS account for the resources that quietly burn money — unattached EBS volumes, idle NAT gateways, old snapshots, unused load balancers, gp2 volumes that should be gp3 — and gives you a dashboard with the exact `aws` CLI command to fix each one.

**100% local.** Your AWS credentials never leave your laptop. No SaaS account. No telemetry. The code is Apache-2.0 — audit it yourself.

![dashboard screenshot](docs/screenshot.png)

## Why another cost tool?

| | aws-cost-optimizer | CloudHealth / Vantage | Komiser |
|---|---|---|---|
| Your creds stay local | ✅ | ❌ (cross-account role to SaaS) | ✅ |
| AWS-specific deep checks | ✅ | ✅ | partial (multi-cloud) |
| Copy-paste fix commands | ✅ | ❌ | ❌ |
| Cost | free | $$$ | free |
| Setup time | 1 `pip install` | onboarding call | install + config |

## Quick start

### Option 1: One command (CLI) — recommended

Installs straight from this repo, so `awsco` lands on your PATH. Use `pipx` for an
isolated install (or swap in `pip`):

```bash
pipx install "git+https://github.com/venkateswarisudalai/aws-cost-optimizer.git#subdirectory=backend"
```

Then:

```bash
awsco scan --demo-data   # see sample findings — no AWS account needed
awsco scan               # scan your real account (read-only)
awsco scan --json        # JSON output for piping
```

### Option 2: Dashboard (clone + run)

The web dashboard is bundled with the repo:

```bash
git clone https://github.com/venkateswarisudalai/aws-cost-optimizer
cd aws-cost-optimizer/backend
pip install -e .
awsco serve              # dashboard at http://localhost:3000
                         # add --demo-data to explore without an AWS account
```

## What it finds (v1)

| Check | Typical savings | Confidence |
|---|---|---|
| Unattached EBS volumes | $0.08/GB/mo each | High |
| Unused Elastic IPs | $3.65/mo each | High |
| EBS snapshots older than 90 days | $0.05/GB/mo each | Medium |
| Idle NAT gateways (no traffic 7d) | $32.40/mo each | High |
| Idle EC2 instances (running, <5% CPU 7d) | full instance cost | Medium |
| Stopped EC2 still paying for EBS | varies | High |
| Idle RDS (no connections 7d) | $12–$200+/mo each | Medium |
| Old manual RDS snapshots (>90 days) | $0.095/GB/mo each | Medium |
| Idle Redshift clusters (no connections 7d) | $180+/mo each | Medium |
| Idle ElastiCache clusters (<2% CPU 7d) | $12–$300+/mo each | Medium |
| Idle provisioned DynamoDB tables (~0 usage 7d) | reserved RCU/WCU cost | Medium |
| Unused ALB/NLB (no targets or 0 reqs) | ~$16/mo each | High |
| gp2 volumes that should be gp3 | 20% on EBS storage | High |
| CloudWatch Log groups without retention | grows unbounded | High |

### FinOps recommendations (v1.1+)

Beyond idle/orphan waste, `awsco` now pulls the same recommendations a FinOps
team lives in — straight from AWS, surfaced next to the waste so the whole
picture is in one dashboard. Each finding carries a **category** so you can
filter:

| Check | Category | Source | What it does |
|---|---|---|---|
| EC2 rightsizing | `rightsizing` | Compute Optimizer | Over-provisioned instances + the cheaper type that still fits the load |
| Reserved Instance recommendations | `commitment` | Cost Explorer | RI purchases that would discount steady EC2/RDS/ElastiCache/Redshift/OpenSearch usage |
| Savings Plans recommendations | `commitment` | Cost Explorer | The hourly Compute/EC2 Savings Plan commitment that maximises discount |
| Cost anomalies | `anomaly` | Cost Anomaly Detection | Unexpected spend spikes by service (one-off impact, tracked separately from savings) |

Notes:
- These are **account-wide** (the Cost Explorer endpoint is global), so they run
  once per scan, not per region.
- They need the services switched on: enroll in **Compute Optimizer**, and have
  at least one **Cost Anomaly Monitor** configured. If a service isn't enabled,
  that check simply returns nothing — no errors.
- Anomalies are *impacts*, not recurring savings, so they don't inflate the
  "monthly savings" headline; their dollar impact is reported on its own.

Each finding ships with:
- The exact `aws` CLI command to fix it
- Whether the fix destroys data (snapshots, volumes)
- Estimated monthly savings (US-east-1 pricing)
- Evidence (last-used timestamp, current utilization)

## Permissions

The IAM policy lives in [`infra/iam-policy.json`](infra/iam-policy.json). It's read-only — no `Delete*`, `Modify*`, or `Create*` actions. You apply the suggested fixes yourself.

Attach it to an IAM user or role, then point `AWS_PROFILE` at it.

## Trust posture

- **No outbound network calls** except to AWS API endpoints. Run with `--audit-mode` to log every network request.
- **No telemetry.** Ever. Not even anonymized counters.
- **Credentials are read from your local `~/.aws/credentials` or env vars.** Never written, never transmitted anywhere except AWS.
- **Install from source.** You install with `pipx install "git+…"` or by cloning — so you can read every line before it ever touches your account.

## Development

```bash
git clone https://github.com/venkateswarisudalai/aws-cost-optimizer
cd aws-cost-optimizer

# Backend
cd backend && pip install -e ".[dev]"
awsco serve --demo-data

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

## Roadmap

- v1.0 — Idle/orphan finder ✅
- v1.1 — Rightsizing (Compute Optimizer integration) ✅
- v1.2 — Cost trends (Cost Explorer)
- v1.3 — Multi-account org scanning
- v1.4 — Anomaly detection (Cost Anomaly Detection) ✅
- v2.0 — Savings Plans / RI recommendations ✅
- Packaging — published PyPI release + a one-line Docker image (in progress)

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The easiest way to help: add a new collector. Each one is ~80 lines of Python.

## License

Apache-2.0. See [LICENSE](LICENSE).
