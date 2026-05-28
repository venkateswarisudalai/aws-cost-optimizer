"""FastAPI server: powers the Next.js dashboard."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from awsco import __version__
from awsco.aws import (
    InlineCredentials,
    account_regions,
    caller_identity,
    enabled_regions,
    list_profiles,
)
from awsco.demo.fixtures import build_demo_scan
from awsco.models import ScanResult
from awsco.scanner import run_scan
from awsco.storage import (
    get_scan,
    latest_scan,
    list_scans,
    save_scan,
)


class AwsCredentials(BaseModel):
    access_key_id: str = Field(min_length=16)
    secret_access_key: str = Field(min_length=1)
    session_token: str | None = None

    def as_inline(self) -> InlineCredentials:
        return {
            "access_key_id": self.access_key_id.strip(),
            "secret_access_key": self.secret_access_key.strip(),
            "session_token": (self.session_token or "").strip() or None,
        }


class ScanRequest(BaseModel):
    profile: str | None = None
    regions: list[str] | None = None
    credentials: AwsCredentials | None = None


class ConnectRequest(BaseModel):
    """Validate a connection before scanning: either a local profile or
    pasted access keys."""

    profile: str | None = None
    credentials: AwsCredentials | None = None


log = logging.getLogger(__name__)


class AppState:
    demo_mode: bool = False
    profile: str | None = None
    regions: list[str] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if AppState.demo_mode:
        # Seed a demo scan on first boot so the dashboard isn't empty.
        existing = latest_scan()
        if existing is None or not existing.is_demo:
            save_scan(build_demo_scan())
    yield


def _demo_regions() -> list[dict[str, object]]:
    """A representative slice of the real catalog for demo mode: a few enabled
    regions plus a couple of not-activated opt-in regions."""
    enabled = ["us-east-1", "us-east-2", "us-west-2", "eu-west-1", "ap-southeast-2"]
    not_opted = ["ap-east-1", "me-south-1", "af-south-1"]
    rows = [
        {"name": r, "opt_in_status": "opt-in-not-required", "enabled": True}
        for r in enabled
    ] + [
        {"name": r, "opt_in_status": "not-opted-in", "enabled": False}
        for r in not_opted
    ]
    return sorted(rows, key=lambda x: str(x["name"]))


def _dev_origins() -> list[str]:
    """Origins allowed in dev. The Next.js dev server runs on :3001 by default
    (see frontend/package.json); :3000 is the bundled-Docker port. An extra
    origin can be supplied via AWSCO_CORS_ORIGIN."""
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    extra = os.environ.get("AWSCO_CORS_ORIGIN")
    if extra:
        origins.append(extra)
    return origins


def create_app() -> FastAPI:
    app = FastAPI(
        title="aws-cost-optimizer",
        version=__version__,
        description="Local-first AWS waste finder.",
        lifespan=lifespan,
    )
    # In Docker we serve the built frontend from the same origin, so CORS is a
    # no-op there. These origins matter only for `npm run dev`.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_dev_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "demo": AppState.demo_mode}

    @app.post("/scan")
    def scan(req: ScanRequest | None = None) -> ScanResult:
        if AppState.demo_mode:
            result = build_demo_scan()
        else:
            profile = (req.profile if req else None) or AppState.profile
            regions = (req.regions if req else None) or AppState.regions
            credentials = req.credentials.as_inline() if (req and req.credentials) else None
            try:
                result = run_scan(
                    profile=profile, regions=regions, credentials=credentials
                )
            except Exception as exc:
                log.exception("scan failed")
                raise HTTPException(
                    status_code=500, detail=f"Scan failed: {exc}"
                ) from exc
        save_scan(result)
        return result

    @app.get("/aws/profiles")
    def aws_profiles():
        if AppState.demo_mode:
            return {"profiles": ["demo"], "demo": True}
        return {"profiles": list_profiles(), "demo": False}

    @app.get("/aws/regions")
    def aws_regions(profile: str | None = Query(default=None)):
        if AppState.demo_mode:
            return {"regions": _demo_regions(), "demo": True}
        try:
            return {"regions": account_regions(profile=profile), "demo": False}
        except Exception as exc:
            log.warning("Could not list regions for profile=%s: %s", profile, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/aws/validate")
    def aws_validate(req: ConnectRequest):
        """Verify a connection works and return the account identity + the
        regions enabled for it. Used by the Connect dialog before scanning."""
        if AppState.demo_mode:
            return {
                "account_id": "123456789012",
                "arn": "arn:aws:iam::123456789012:user/demo",
                "regions": _demo_regions(),
                "demo": True,
            }
        credentials = req.credentials.as_inline() if req.credentials else None
        try:
            ident = caller_identity(profile=req.profile, credentials=credentials)
            regions = account_regions(profile=req.profile, credentials=credentials)
        except Exception as exc:
            log.warning("connection validation failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=400,
                detail=f"Could not connect to AWS: {exc}",
            ) from exc
        return {
            "account_id": ident["account_id"],
            "arn": ident["arn"],
            "regions": regions,
            "demo": False,
        }

    @app.get("/scans")
    def scans(limit: int = Query(default=50, le=200)):
        return {"scans": list_scans(limit=limit)}

    @app.get("/scans/latest")
    def latest():
        result = latest_scan()
        if not result:
            return JSONResponse(
                status_code=404, content={"detail": "No scans yet. POST /scan first."}
            )
        return result

    @app.get("/scans/{scan_id}")
    def by_id(scan_id: str):
        result = get_scan(scan_id)
        if not result:
            raise HTTPException(status_code=404, detail="Scan not found")
        return result

    # Static frontend (mounted only if the built dir exists — Docker case)
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
