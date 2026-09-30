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
| io1 volumes gp3 can serve (≤16k IOPS) | often 60–80% of the volume | High |
| Secrets Manager secrets unread for 90+ days | $0.40/mo each | Medium |
| Idle interface VPC endpoints (PrivateLink) | ~$7.20/mo per AZ each | Medium |
| Idle Transit Gateway attachments | ~$36/mo each | Medium |
| Idle Site-to-Site VPN connections | ~$36/mo each | Medium |
| **Abandoned VPCs** (no workload, no traffic, no recent CloudTrail activity) | sum of its NAT / LB / endpoints / IPs | Medium |
| Unused security groups (hygiene, $0 — flags ones open to 0.0.0.0/0) | security, not cost | Medium |

**Lookback.** Idle checks read CloudWatch history for 7 days by default; pick 14/30/60
in the dashboard or pass `awsco scan --lookback-days 30`. Use 30+ before deleting
anything — 7 days misses monthly jobs.

**Every finding explains itself.** Expand a row for the recommendation, the risks,
what to check before acting, and how to undo it (or a clear "not reversible").

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
| Cost Optimization Hub | all | Cost Optimization Hub | AWS's own aggregator: Graviton moves, Lambda/ECS/RDS/EBS rightsizing, idle resources, commitments |

**Spend baseline.** Each scan also pulls 30-day spend by service, month-to-date
and this month's forecast from Cost Explorer, so the dashboard shows what the
bill would be after the fixes. (AWS bills $0.01 per Cost Explorer request.)

**No double counting.** When two findings are alternatives, like stopping an idle
instance versus rightsizing it, or a Compute Savings Plan versus EC2 RIs for the
same usage, only the bigger one counts toward totals. The other is shown as an
alternative.

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

## Download the findings

**Download** above the findings table saves exactly the rows you're looking at
(filters apply, so pick "Safe to apply" first if that's what you're handing off):

- **PDF**: a report to share — savings, current bill, "after fixes", what's safe to
  apply now, a summary table, then one card per finding with the risk, a
  before-you-act checklist, the fix command and Approved by / Date / Change ticket
  lines. Opens the print dialog; choose **Save as PDF**.
- **CSV** for Excel / Google Sheets: every field, including the recommendation,
  risks, undo steps, fix command, owner and owner's answer.
- **Markdown**: a summary table plus one section per finding with a
  "before you act" checklist, ready to paste into a change ticket or report.
- **JSON** for scripts.

Files are built in your browser and saved locally; nothing is uploaded. From the
CLI, `awsco scan --json > findings.json` does the same.

## Ask owners on Slack (optional)

Before deleting anything, ask the person who created it. Each finding shows its
**owner**, taken from an `Owner` / `CreatedBy` / `Team` / `Email` tag or, failing that,
from the CloudTrail event that created it (last 90 days). **Ask on Slack** posts:

> *@priya, is this still needed?* Idle EC2 'analytics-box' (m5.2xlarge)… React ✅ to keep
> it, or 🗑️ if it's OK to delete.

in your team channel (or as a DM). **Check Slack replies** reads the reactions
back, and the answer (who, when, and any thread reply) is stored locally as the
owner-confirmation evidence a SOC 2 change ticket needs. Only the owner's reaction
counts when the owner is known, and ✅ keep beats 🗑️ delete. Nothing is ever
deleted automatically.

Setup: create a Slack app, add the bot scopes listed in [`.env.example`](.env.example),
install it, invite the bot to your channel, then:

```bash
export AWSCO_SLACK_BOT_TOKEN=xoxb-…   # never commit this
export AWSCO_SLACK_CHANNEL=C0123ABCD
awsco serve
```

Without a token the button shows a preview of the message instead of sending it.
It uses Slack's Web API only (outbound HTTPS), so the local server never has to be
reachable from the internet.

## Permissions

The IAM policy lives in [`infra/iam-policy.json`](infra/iam-policy.json). It's read-only — no `Delete*`, `Modify*`, or `Create*` actions. You apply the suggested fixes yourself.

Attach it to an IAM user or role, then point `AWS_PROFILE` at it.

## Trust posture

- **Account guard.** Enter the 12-digit account ID in the Connect dialog; every scan is refused if the keys belong to a different account.
- **Key hygiene warnings.** Root keys and long-lived `AKIA…` keys get a warning; temporary `ASIA…` keys are recommended.
- **Loopback only.** `awsco serve` binds `127.0.0.1` by default (Docker publishes on `127.0.0.1:3000`), and a Host-header allowlist blocks DNS-rebinding. Use `AWSCO_ALLOWED_HOSTS` to add hostnames.

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
