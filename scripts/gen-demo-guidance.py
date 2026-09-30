"""Regenerate frontend/app/lib/demoGuidance.json from the backend's guidance.

The hosted demo is a static build with no Python backend, so it can't compute
guidance at runtime. This bakes the guidance for every backend demo finding,
keyed by "check_id|resource_id", for demoData.ts to attach.

    cd backend && PYTHONPATH=. .venv/bin/python ../scripts/gen-demo-guidance.py
"""

import json
from pathlib import Path

from awsco.demo.fixtures import build_demo_scan

out = Path(__file__).resolve().parent.parent / "frontend/app/lib/demoGuidance.json"
data = {f"{f.check_id}|{f.resource_id}": f.guidance for f in build_demo_scan().findings}
out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
print(f"wrote {len(data)} entries to {out}")
