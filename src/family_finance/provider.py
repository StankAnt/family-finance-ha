from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

import httpx
import jwt

from .config import Settings
from .secrets import FinanceError, read_private


class EnableBankingClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 psu_headers: dict[str, str] | None = None):
        self.settings = settings
        self.key = read_private(settings.key_file)
        self.http = httpx.Client(base_url=settings.api_base, timeout=20, follow_redirects=False,
                                 transport=transport)
        self.last_account_call = 0.0
        self.psu_headers = psu_headers

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, *, params: dict[str, str] | None = None,
                body: dict[str, Any] | None = None,
                psu_headers: dict[str, str] | None = None) -> dict[str, Any]:
        if method not in {"GET", "POST"} or not path.startswith("/") or "//" in path:
            raise FinanceError("Invalid API request")
        now = int(datetime.now(timezone.utc).timestamp())
        token = jwt.encode({"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                            "iat": now, "exp": now + 600}, self.key, algorithm="RS256",
                           headers={"typ": "JWT", "kid": self.settings.application_id})
        if path.startswith("/accounts/"):
            wait = 2 - (time.monotonic() - self.last_account_call)
            if wait > 0:
                time.sleep(wait)
            self.last_account_call = time.monotonic()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        active_psu_headers = psu_headers if psu_headers is not None else (
            self.psu_headers if path.startswith("/accounts/") else None)
        if active_psu_headers:
            if not path.startswith("/accounts/") or set(active_psu_headers) - {
                    "Psu-Ip-Address", "Psu-User-Agent", "Psu-Accept-Language"}:
                raise FinanceError("Invalid PSU headers")
            headers.update(active_psu_headers)
        try:
            response = self.http.request(method, path, params=params, json=body,
                                         headers=headers)
        except httpx.RequestError:
            raise FinanceError("Could not reach Enable Banking API") from None
        if response.status_code >= 400 or response.is_redirect:
            hint = " (rate limited)" if response.status_code == 429 else ""
            raise FinanceError(f"Enable Banking returned HTTP {response.status_code}{hint}")
        if len(response.content) > 5_000_000:
            raise FinanceError("API response exceeded size limit")
        try:
            result = response.json()
        except ValueError as exc:
            raise FinanceError("API returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise FinanceError("API returned unexpected JSON structure")
        return result
