"""Loopback callback receiver for separate production and sandbox profiles."""

from __future__ import annotations

import hmac
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import uvicorn
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .accounting import sync_nbp
from .auth import AuthorizationService
from .config import Settings
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private, write_private
from .reader import online_account_types, online_headers
from .classification import classify, pair_transfers, seed
from .ai_worker import ProductionDecisionRunner
from .sync import database_engine, sync_ais
from .models import AccountBalanceSnapshot, BankConnection, SyncRun, Transaction
from .notifications import count_new_unclassified, publish_new_unclassified
from . import onboarding


def create_app(settings: Settings, service: AuthorizationService | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    primary_service = service

    def add_callback(profile: str, callback_url: str, fixed_service: AuthorizationService | None) -> None:
        path = urlsplit(callback_url).path
        host = urlsplit(callback_url).netloc

        def callback(request: Request) -> HTMLResponse:
            params = request.query_params
            status, message = 400, "Authorization could not be completed. Check the local service status."
            if (request.headers.get("host") == host
                    and len(params.getlist("state")) == 1
                    and len(params.getlist("code")) == 1
                    and "error" not in params):
                client = None
                try:
                    selected_service = fixed_service
                    if selected_service is None:
                        selected_settings = Settings.load(profile)
                        client = EnableBankingClient(selected_settings)
                        selected_service = AuthorizationService(selected_settings, client)
                    selected_service.complete(params["state"], params["code"])
                    status, message = 200, "Bank access authorized. You can close this tab."
                except (FinanceError, OSError, UnicodeError):
                    pass
                finally:
                    if client is not None:
                        client.close()
            body = (f'<!doctype html><html lang="en"><meta charset="utf-8">'
                    f'<title>Family Finance</title><body><p>{message}</p></body></html>')
            return HTMLResponse(body, status_code=status, headers={
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'", "X-Content-Type-Options": "nosniff"})

        app.add_api_route(path, callback, methods=["GET"], include_in_schema=False)

    add_callback(settings.environment, settings.callback_url, primary_service)
    if settings.environment == "production":
        sync_lock = Lock()
        ai_runner = ProductionDecisionRunner(settings.project_dir)
        rate_limited_until = [0.0]
        cooldown_file = settings.project_dir / "secrets" / "production" / "bank_rate_limit_until"

        def check_key(request: Request) -> None:
            key = read_private(settings.project_dir / "secrets" / "dashboard_api_key").decode().strip()
            if not hmac.compare_digest(request.headers.get("X-Finance-Key", ""), key):
                raise HTTPException(status_code=403, detail="Forbidden")

        def check_internal(request: Request) -> None:
            check_key(request)
            if request.headers.get("content-length") not in (None, "0"):
                raise HTTPException(status_code=400, detail="Unexpected request body")

        @app.post("/internal/onboarding", include_in_schema=False)
        def onboarding_command(request: Request, body: dict) -> dict:
            check_key(request)
            if len(str(body)) > 40000 or set(body) != {"operation", "payload"} or not isinstance(body["payload"], dict):
                raise HTTPException(status_code=400, detail="Invalid setup request")
            operation, payload = body["operation"], body["payload"]
            try:
                if operation == "setup_status" and not payload:
                    return onboarding.status(settings.project_dir)
                if operation == "setup_credentials":
                    return onboarding.configure(settings.project_dir, payload)
                if operation == "setup_generate_key" and not payload:
                    return onboarding.generate_keypair(settings.project_dir)
                if operation == "setup_public_certificate" and not payload:
                    return onboarding.public_certificate(settings.project_dir)
                if operation == "auth_start":
                    return onboarding.start_authorization(settings.project_dir, payload)
                if operation == "auth_banks" and not payload:
                    return onboarding.list_banks(settings.project_dir)
                if operation == "auth_complete":
                    return onboarding.complete_authorization(settings.project_dir, payload)
            except FinanceError as exc:
                raise HTTPException(status_code=400, detail=str(exc)[:180]) from None
            except (OSError, UnicodeError):
                raise HTTPException(status_code=400, detail="Local setup file operation failed") from None
            raise HTTPException(status_code=400, detail="Unknown setup operation")

        @app.post("/internal/ai-production", include_in_schema=False)
        def start_ai_production(request: Request) -> dict:
            check_internal(request)
            if not onboarding.ai_enabled(settings.project_dir):
                raise HTTPException(status_code=400, detail="OpenAI classification is disabled in settings")
            return {"started": ai_runner.start(), **ai_runner.status()}

        @app.get("/internal/ai-status", include_in_schema=False)
        def ai_status(request: Request) -> dict:
            check_internal(request)
            return ai_runner.status()

        @app.post("/internal/cash-fx", include_in_schema=False)
        def cash_fx(request: Request, body: dict) -> dict:
            check_key(request)
            month = body.get("month") if set(body) == {"month"} else None
            if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                raise HTTPException(status_code=400, detail="Invalid cash FX month")
            year, number = map(int, month.split("-"))
            if year < 2002 or year > 9998:
                raise HTTPException(status_code=400, detail="Cash FX month is unavailable")
            start = date(year, number, 1)
            end = min(date.today(), date(year + (number == 12), number % 12 + 1, 1) - timedelta(days=1))
            if start > end or start < date(2002, 1, 2):
                raise HTTPException(status_code=400, detail="Cash FX month is unavailable")
            engine = database_engine(settings.project_dir / "secrets" / "production_database_url_host")
            try:
                with Session(engine) as db, db.begin():
                    added = sync_nbp(db, start, end)
                return {"rates_added": added, "month": month}
            except FinanceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)[:180]) from None
            finally:
                engine.dispose()

        @app.post("/internal/inspect-accounts", include_in_schema=False)
        def inspect_accounts(request: Request) -> dict:
            check_internal(request)
            try:
                return online_account_types(settings,
                                            request.headers.get("X-Finance-PSU-IP", ""),
                                            request.headers.get("X-Finance-PSU-User-Agent", ""))
            except FinanceError as exc:
                raise HTTPException(status_code=429 if "HTTP 429" in str(exc) else 400,
                                    detail=str(exc)) from None

        def run_sync(psu_headers: dict[str, str] | None, *, background: bool) -> dict:
            if monotonic() < rate_limited_until[0]:
                raise HTTPException(status_code=429, detail="Bank rate limit; try again later")
            if cooldown_file.exists():
                cooldown = datetime.fromisoformat(read_private(cooldown_file).decode().strip())
                if datetime.now(timezone.utc) < cooldown:
                    raise HTTPException(status_code=429, detail="Bank rate limit; try again later")
            if not sync_lock.acquire(blocking=False):
                raise HTTPException(status_code=409, detail="Bank sync is already running")
            engine = None
            try:
                engine = database_engine(settings.project_dir / "secrets" / "production_database_url_host")
                with Session(engine) as db:
                    if background:
                        latest = db.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
                        has_balances = latest and db.scalar(select(AccountBalanceSnapshot.id).where(
                            AccountBalanceSnapshot.sync_run_id == latest.id).limit(1)) is not None
                        connection = db.get(BankConnection, latest.connection_id) if latest else None
                        if latest and connection and connection.consent_status == "AUTHORIZED" and latest.status == "SUCCESS" and has_balances and latest.started_at and (datetime.now(timezone.utc) -
                                latest.started_at.astimezone(timezone.utc)) < timedelta(hours=6):
                            return {"skipped": "Recent bank sync"}
                    imported_before = db.scalar(select(func.max(Transaction.imported_at)))
                today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
                accounts, rows = sync_ais(engine, settings,
                                          initial_from_date=today - timedelta(days=90),
                                          psu_headers=psu_headers,
                                          known_accounts_only=background)
                fx_rates_updated = True
                try:
                    with Session(engine) as db, db.begin():
                        sync_nbp(db, today - timedelta(days=97), today)
                except FinanceError:
                    fx_rates_updated = False
                with Session(engine) as db, db.begin():
                    seed(db)
                    confirmed, review = pair_transfers(db)
                    classify(db)
                    new_unclassified = count_new_unclassified(
                        db, imported_before or datetime(1970, 1, 1, tzinfo=timezone.utc))
                if hasattr(ai_runner, "add_completion_callback"):
                    ai_runner.add_completion_callback(
                        lambda: publish_new_unclassified(settings.project_dir, imported_before or datetime(1970, 1, 1, tzinfo=timezone.utc)))
                ai_started = ai_runner.start() if onboarding.ai_enabled(settings.project_dir) else False
                return {"accounts": accounts, "transactions_seen": rows,
                        "transfers_confirmed": confirmed, "transfers_for_review": review,
                        "new_unclassified": new_unclassified,
                        "ai_started": ai_started, "fx_rates_updated": fx_rates_updated}
            except FinanceError as exc:
                if "HTTP 429" in str(exc):
                    rate_limited_until[0] = monotonic() + 6 * 60 * 60
                    write_private(cooldown_file, (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat())
                    raise HTTPException(status_code=429, detail="Bank rate limit; try again later") from None
                raise HTTPException(status_code=400, detail=str(exc)) from None
            finally:
                if engine is not None:
                    engine.dispose()
                sync_lock.release()

        @app.post("/internal/sync-production", include_in_schema=False)
        def sync_production(request: Request) -> dict:
            check_internal(request)
            try:
                headers = online_headers(request.headers.get("X-Finance-PSU-IP", ""),
                                         request.headers.get("X-Finance-PSU-User-Agent", ""))
            except FinanceError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            return run_sync(headers, background=False)

        @app.post("/internal/sync-background", include_in_schema=False)
        def sync_background(request: Request) -> dict:
            check_internal(request)
            if request.headers.get("X-Finance-PSU-IP") or request.headers.get("X-Finance-PSU-User-Agent"):
                raise HTTPException(status_code=400, detail="Background sync cannot use PSU headers")
            return run_sync(None, background=True)
    return app


def main() -> None:
    settings = Settings.load("production", allow_unconfigured=True)
    uvicorn.run(create_app(settings), host=settings.listen_host, port=settings.listen_port,
                access_log=False, log_level="warning", server_header=False)
