from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import hmac
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from .config import Settings
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private, uuid_text, write_private
from .session_store import record_session


class AuthorizationService:
    def __init__(self, settings: Settings, client: EnableBankingClient):
        self.settings = settings
        self.client = client

    def start(self, bank_name: str, redirect_url: str | None = None) -> Path:
        redirect_url = redirect_url or self.settings.callback_url
        if redirect_url != self.settings.callback_url:
            raise FinanceError("Redirect URL does not match selected profile")
        app = self.client.request("GET", "/application")
        if app.get("environment") != self.settings.environment.upper():
            raise FinanceError("Application environment does not match selected profile")
        if redirect_url not in app.get("redirect_urls", []):
            raise FinanceError("Redirect URL is not registered on this application")
        banks = self.client.request("GET", "/aspsps", params={"country": "PL"}).get("aspsps", [])
        selected_bank = next((bank for bank in banks if isinstance(bank, dict) and
                              bank.get("name") == bank_name and bank.get("country") == "PL"), None)
        if selected_bank is None:
            raise FinanceError("Bank is not in the Polish ASPSP list")
        maximum = selected_bank.get("maximum_consent_validity", 180 * 86400)
        if type(maximum) is not int or maximum <= 0:
            raise FinanceError("Bank consent validity is unavailable")
        state = secrets.token_urlsafe(32)
        valid_until = (datetime.now(timezone.utc) + timedelta(seconds=min(maximum, 180 * 86400))).isoformat()
        response = self.client.request("POST", "/auth", body={
            "access": {"valid_until": valid_until, "balances": True, "transactions": True},
            "aspsp": {"name": bank_name, "country": "PL"}, "state": state,
            "redirect_url": redirect_url, "psu_type": "personal"})
        url = response.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "https":
            raise FinanceError("Authorization URL missing or invalid")
        # Store state only once a valid provider response exists.
        write_private(self.settings.secrets_dir / "auth_state", state)
        url_file = self.settings.secrets_dir / "authorization_url"
        write_private(url_file, url + "\n")
        return url_file

    def complete(self, supplied_state: str, code: str) -> int:
        if not supplied_state or not code or len(code) > 4096:
            raise FinanceError("Callback parameters missing or invalid")
        lock_file = self.settings.secrets_dir / "callback.lock"
        lock_file.touch(mode=0o600, exist_ok=True)
        if lock_file.stat().st_mode & 0o077:
            raise FinanceError("Callback lock has unsafe permissions")
        with lock_file.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state_file = self.settings.secrets_dir / "auth_state"
            expected = read_private(state_file).decode("utf-8").strip()
            if not hmac.compare_digest(supplied_state, expected):
                raise FinanceError("Callback state mismatch")
            app = self.client.request("GET", "/application")
            if app.get("environment") != self.settings.environment.upper():
                raise FinanceError("Application environment does not match selected profile")
            result = self.client.request("POST", "/sessions", body={"code": code})
            session_id = uuid_text(result.get("session_id"))
            accounts = result.get("accounts")
            if not isinstance(accounts, list):
                raise FinanceError("Session response has no account list")
            record_session(self.settings, session_id)
            state_file.unlink()
            (self.settings.secrets_dir / "authorization_url").unlink(missing_ok=True)
            return len(accounts)

    def complete_from_files(self) -> int:
        state_file = self.settings.secrets_dir / "callback_state"
        code_file = self.settings.secrets_dir / "callback_code"
        supplied_state = read_private(state_file).decode("utf-8").strip()
        code = read_private(code_file).decode("utf-8").strip()
        count = self.complete(supplied_state, code)
        state_file.unlink()
        code_file.unlink()
        return count
