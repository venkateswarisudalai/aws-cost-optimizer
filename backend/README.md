# aws-cost-optimizer — backend

Python package powering the dashboard and CLI. See the [top-level README](../README.md) for the user-facing docs.

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

awsco scan --demo-data
awsco serve --demo-data   # dashboard at :3000
```

## Layout

- `awsco/collectors/` — one module per waste check
- `awsco/scanner.py` — orchestrator (parallel across regions)
- `awsco/server.py` — FastAPI app
- `awsco/cli.py` — Click CLI entrypoint
- `awsco/storage.py` — SQLite scan history
