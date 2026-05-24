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
| Setup time | 1 `docker run` | onboarding call | install + config |

## Quick start

### Option 1: Docker (recommended)

```bash
docker run --rm -p 3000:3000 \
  -v ~/.aws:/root/.aws:ro \
  -e AWS_PROFILE=default \
  ghcr.io/venkateswarisudalai/aws-cost-optimizer:latest
```

Open <http://localhost:3000>.

### Option 2: pipx

```bash
pipx install aws-cost-optimizer
awsco serve            # launches the dashboard at :3000
awsco scan             # one-shot CLI scan, prints findings as a table
awsco scan --json      # JSON output for piping
```

### Option 3: try it with no AWS account

```bash
docker run --rm -p 3000:3000 \
  ghcr.io/venkateswarisudalai/aws-cost-optimizer:latest \
  --demo-data
```

## What it finds (v1)

| Check | Typical savings | Confidence |
|---|---|---|
| Unattached EBS volumes | $0.08/GB/mo each | High |
| Unused Elastic IPs | $3.65/mo each | High |
| EBS snapshots older than 90 days | $0.05/GB/mo each | Medium |
| Idle NAT gateways (no traffic 7d) | $32.40/mo each | High |
| Stopped EC2 still paying for EBS | varies | High |
| Idle RDS (no connections 7d) | $12–$200+/mo each | Medium |
| Unused ALB/NLB (no targets or 0 reqs) | ~$16/mo each | High |
| gp2 volumes that should be gp3 | 20% on EBS storage | High |
| CloudWatch Log groups without retention | grows unbounded | High |

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
- **The Docker image is built from this repo with reproducible builds via GitHub Actions** — verify the SHA matches.

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

- v1.0 — Idle/orphan finder (current)
- v1.1 — Rightsizing (Compute Optimizer integration)
- v1.2 — Cost trends (Cost Explorer)
- v1.3 — Multi-account org scanning
- v1.4 — Anomaly detection
- v2.0 — Savings Plans / RI recommendations

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The easiest way to help: add a new collector. Each one is ~80 lines of Python.

## License

Apache-2.0. See [LICENSE](LICENSE).
