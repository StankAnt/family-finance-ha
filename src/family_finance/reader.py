"""Bounded, read-only AIS diagnostics. Does not persist bank payloads."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from collections import Counter
from ipaddress import ip_address
from typing import Any

from .provider import EnableBankingClient
from .secrets import FinanceError, uuid_text
from .secrets import read_private
from .config import Settings
from .session_store import authorized_sessions


def transaction_summary(rows: list[dict[str, Any]]) -> str:
    dates = []
    for row in rows:
        raw = row.get("booking_date") or row.get("value_date") or row.get("transaction_date")
        if isinstance(raw, str):
            try:
                dates.append(date.fromisoformat(raw[:10]))
            except ValueError:
                pass
    span = f"{min(dates)}..{max(dates)}" if dates else "dates unavailable"
    return f"count={len(rows)}, date range={span}"


def inspect(client: EnableBankingClient, session_id: str, days: int) -> list[str]:
    if not 1 <= days <= 30:
        raise FinanceError("--days must be between 1 and 30")
    session = client.request("GET", f"/sessions/{uuid_text(session_id)}")
    accounts = session.get("accounts")
    if not isinstance(accounts, list):
        raise FinanceError("Session response has no account list")
    result = [f"Session: status={session.get('status', 'unknown')}; authorized accounts={len(accounts)}"]
    if session.get("status") != "AUTHORIZED":
        return result
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    for index, raw_id in enumerate(accounts, 1):
        account_id = uuid_text(raw_id)
        details = client.request("GET", f"/accounts/{account_id}/details")
        balances = client.request("GET", f"/accounts/{account_id}/balances").get("balances")
        if not isinstance(balances, list):
            raise FinanceError("Unexpected balance response structure")
        rows: list[dict[str, Any]] = []
        continuation = None
        for _ in range(3):
            params = {"date_from": start.isoformat(), "date_to": end.isoformat()}
            if continuation:
                params["continuation_key"] = continuation
            page = client.request("GET", f"/accounts/{account_id}/transactions", params=params)
            transactions = page.get("transactions")
            if not isinstance(transactions, list) or not all(isinstance(x, dict) for x in transactions):
                raise FinanceError("Unexpected transactions response structure")
            rows.extend(transactions)
            continuation = page.get("continuation_key")
            if not continuation:
                break
        currency = details.get("currency", "unknown")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            currency = "unknown"
        result.append(f"Account {index}: currency={currency}; balances={len(balances)}; "
                      f"transactions {transaction_summary(rows)}; complete={not bool(continuation)}")
    return result


def online_headers(user_ip: str, user_agent: str) -> dict[str, str]:
    """Validate actual browser identity forwarded by the authenticated HA bridge."""
    try:
        ip_address(user_ip)
    except ValueError as exc:
        raise FinanceError("Browser IP is unavailable") from exc
    if not isinstance(user_agent, str) or not 1 <= len(user_agent) <= 512 or not user_agent.isascii() or any(
            ord(char) < 32 or ord(char) == 127 for char in user_agent):
        raise FinanceError("Browser User-Agent is unavailable")
    return {"Psu-Ip-Address": user_ip, "Psu-User-Agent": user_agent}


def online_account_types(settings: Settings, user_ip: str, user_agent: str) -> dict:
    """Read only account types for a user-triggered request; never expose identifiers."""
    headers = online_headers(user_ip, user_agent)
    client = EnableBankingClient(settings)
    try:
        accounts = []
        for session in authorized_sessions(settings, client):
            session_accounts = session.get("accounts")
            if not isinstance(session_accounts, list):
                raise FinanceError("Invalid authorized account list")
            for raw_id in session_accounts:
                uid = uuid_text(raw_id)
                if uid not in accounts:
                    accounts.append(uid)
        if len(accounts) > 40:
            raise FinanceError("Too many authorized accounts")
        counts: Counter[str] = Counter()
        for raw_id in accounts:
            details = client.request("GET", f"/accounts/{raw_id}/details",
                                     psu_headers=headers)
            kind = details.get("cash_account_type")
            counts[kind if isinstance(kind, str) and kind in {
                "CACC", "CASH", "CARD", "LOAN", "SVGS", "OTHR"} else "UNKNOWN"] += 1
        return {"account_count": len(accounts), "types": dict(sorted(counts.items()))}
    finally:
        client.close()
