"""FastAPI server: powers the Next.js dashboard."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from awsco import __version__
from awsco.aws import (
    InlineCredentials,
    account_regions,
    caller_identity,
    enabled_regions,
    list_profiles,
)
from awsco.demo.fixtures import build_demo_scan
from awsco import slack
from awsco.guidance import attach_guidance
from awsco.models import ScanResult
from awsco.regions import DEFAULT_ENABLED, commercial_regions
from awsco.scanner import AccountMismatchError, run_scan
from awsco.storage import (
    get_scan,
    latest_scan,
    list_confirmations,
    list_scans,
    save_confirmation,
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


# 12-digit AWS account ID the user expects; scans refuse any other account.
AccountId = Annotated[str, StringConstraints(pattern=r"^\d{12}$")]


class ScanRequest(BaseModel):
    profile: str | None = None
    regions: list[str] | None = None
    credentials: AwsCredentials | None = None
    expected_account_id: AccountId | None = None
    lookback_days: int = Field(default=7, ge=1, le=60)


class AskOwnerRequest(BaseModel):
    # Build the Slack message without sending it (always true in demo mode
    # or when no bot token is configured).
    dry_run: bool = False


class ConnectRequest(BaseModel):
    """Validate a connection before scanning: either a local profile or
    pasted access keys."""

    profile: str | None = None
    credentials: AwsCredentials | None = None
    expected_account_id: AccountId | None = None


def credential_warnings(arn: str, access_key_id: str | None) -> list[str]:
    """Plain-language risks of the identity the user connected with."""
    warnings: list[str] = []
    if arn.endswith(":root"):
        warnings.append(
            "These are ROOT account keys. Root keys can do anything, including close "
            "the account. Create an IAM user or role with infra/iam-policy.json "
            "(read-only) and delete the root keys."
        )
    if access_key_id and access_key_id.startswith("AKIA"):
        warnings.append(
            "These are long-lived access keys. Prefer temporary keys (ASIA…, from "
            "`aws sts get-session-token` or SSO) so a leak expires on its own."
        )
    return warnings


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
    """The full commercial region catalog, as a demo account that has opted in
    to every region (so the dashboard shows all of them scannable)."""
    return [
        {
            "name": r,
            "opt_in_status": "opt-in-not-required" if r in DEFAULT_ENABLED else "opted-in",
            "enabled": True,
        }
        for r in commercial_regions()
    ]


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


def _with_guidance(result: ScanResult) -> ScanResult:
    """Scans saved before guidance existed get it filled in on read."""
    missing = [f for f in result.findings if f.guidance is None]
    if missing:
        attach_guidance(missing)
    return result


def _allowed_hosts() -> list[str]:
    """Host headers the server answers to. Blocks DNS-rebinding: a malicious web
    page can't point its own hostname at 127.0.0.1 and drive this API (which
    can use your local AWS profiles). Extend via AWSCO_ALLOWED_HOSTS."""
    # IPv4 loopback only: `awsco serve` binds 127.0.0.1, so IPv6 ([::1])
    # clients can't reach it anyway (and Starlette can't match bracketed hosts).
    hosts = ["localhost", "127.0.0.1", "testserver"]
    extra = os.environ.get("AWSCO_ALLOWED_HOSTS")
    if extra:
        hosts += [h.strip() for h in extra.split(",") if h.strip()]
    return hosts


def create_app() -> FastAPI:
    app = FastAPI(
        title="aws-cost-optimizer",
        version=__version__,
        description="Local-first AWS waste finder.",
        lifespan=lifespan,
    )
    # In Docker we serve the built frontend from the same origin, so CORS is a
    # no-op there. These origins matter only for `npm run dev`.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
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
            # Honour a region filter so the dashboard's per-region switcher
            # behaves the same in demo mode as against a real account.
            requested = req.regions if req else None
            if requested:
                wanted = set(requested)
                result.findings = [f for f in result.findings if f.region in wanted]
                result.regions_scanned = [
                    r for r in result.regions_scanned if r in wanted
                ]
        else:
            profile = (req.profile if req else None) or AppState.profile
            regions = (req.regions if req else None) or AppState.regions
            credentials = req.credentials.as_inline() if (req and req.credentials) else None
            try:
                result = run_scan(
                    profile=profile,
                    regions=regions,
                    credentials=credentials,
                    expected_account_id=req.expected_account_id if req else None,
                    lookback_days=req.lookback_days if req else None,
                )
            except AccountMismatchError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
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
                "warnings": [],
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
        if req.expected_account_id and req.expected_account_id != ident["account_id"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"These credentials belong to account {ident['account_id']}, "
                    f"not {req.expected_account_id}. Check the account ID or the keys."
                ),
            )
        return {
            "account_id": ident["account_id"],
            "arn": ident["arn"],
            "regions": regions,
            "warnings": credential_warnings(
                ident["arn"], credentials["access_key_id"] if credentials else None
            ),
            "demo": False,
        }

    # --- Slack owner confirmations -------------------------------------------

    @app.get("/slack/status")
    def slack_status():
        cfg = slack.config()
        return {
            "configured": cfg["configured"],
            "channel": cfg["channel"],
            "demo": AppState.demo_mode,
        }

    @app.post("/findings/{finding_id}/ask-owner")
    def ask_owner(finding_id: str, req: AskOwnerRequest | None = None):
        scan = latest_scan()
        finding = next((f for f in scan.findings if f.id == finding_id), None) if scan else None
        if finding is None:
            raise HTTPException(status_code=404, detail="Finding not in the latest scan")
        simulate = AppState.demo_mode or not slack.config()["configured"]
        dry_run = simulate or (req.dry_run if req else False)
        try:
            result = slack.ask_owner(finding, dry_run=dry_run)
        except slack.SlackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result["sent"] or AppState.demo_mode:
            save_confirmation({
                "finding_id": finding.id,
                "scan_id": scan.scan_id,
                "check_id": finding.check_id,
                "resource_id": finding.resource_id,
                "region": finding.region,
                "owner_name": (finding.owner or {}).get("name"),
                "owner_slack_id": result.get("owner_slack_id"),
                "channel": result.get("channel") or ("demo" if AppState.demo_mode else None),
                "message_ts": result.get("ts"),
                "status": "pending",
                "asked_at": datetime.now(timezone.utc).isoformat(),
            })
        return {
            **result,
            "simulated": simulate,
            "reason": (
                "demo mode" if AppState.demo_mode
                else "AWSCO_SLACK_BOT_TOKEN not set" if simulate else None
            ),
        }

    @app.post("/confirmations/sync")
    def sync_confirmations():
        """Read reactions for every pending ask and record the answers."""
        updated = 0
        errors: list[str] = []
        for row in list_confirmations():
            if row["status"] != "pending":
                continue
            is_demo_row = row["channel"] == "demo"
            if AppState.demo_mode != is_demo_row:
                # Demo mode must never write fake answers over real asks that
                # share this DB (the SOC 2 audit trail), and real sync skips
                # rehearsal rows.
                continue
            if AppState.demo_mode:
                # Sample answer so the flow can be rehearsed end to end.
                answer = {"status": "delete_ok", "responder": "demo-teammate",
                          "note": "(demo) Left over from the 2024 migration, fine to remove."}
            elif row["channel"] and row["message_ts"]:
                try:
                    answer = slack.read_answer(
                        row["channel"], row["message_ts"], row["owner_slack_id"]
                    )
                except slack.SlackError as exc:
                    errors.append(f"{row['resource_id']}: {exc}")
                    continue
            else:
                continue
            if answer["status"] == "pending":
                continue
            save_confirmation({
                **row, **answer, "answered_at": datetime.now(timezone.utc).isoformat()
            })
            updated += 1
        return {"updated": updated, "errors": errors, "confirmations": list_confirmations()}

    @app.get("/confirmations")
    def confirmations():
        return {"confirmations": list_confirmations()}

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
        return _with_guidance(result)

    @app.get("/scans/{scan_id}")
    def by_id(scan_id: str):
        result = get_scan(scan_id)
        if not result:
            raise HTTPException(status_code=404, detail="Scan not found")
        return _with_guidance(result)

    # Static frontend (mounted only if the built dir exists — Docker case)
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
