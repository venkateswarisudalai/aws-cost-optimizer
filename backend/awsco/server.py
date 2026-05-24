"""FastAPI server: powers the Next.js dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from awsco import __version__
from awsco.demo.fixtures import build_demo_scan
from awsco.models import ScanResult
from awsco.scanner import run_scan
from awsco.storage import (
    DEFAULT_DB_PATH,
    get_scan,
    latest_scan,
    list_scans,
    save_scan,
)

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="aws-cost-optimizer",
        version=__version__,
        description="Local-first AWS waste finder.",
        lifespan=lifespan,
    )
    # Dev frontend runs on :3000 (Next.js). In Docker we serve the built
    # frontend from the same origin, so CORS becomes a no-op anyway.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "demo": AppState.demo_mode}

    @app.post("/scan")
    def scan() -> ScanResult:
        if AppState.demo_mode:
            result = build_demo_scan()
        else:
            try:
                result = run_scan(
                    profile=AppState.profile, regions=AppState.regions
                )
            except Exception as exc:
                log.exception("scan failed")
                raise HTTPException(
                    status_code=500, detail=f"Scan failed: {exc}"
                ) from exc
        save_scan(result)
        return result

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
