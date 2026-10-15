from __future__ import annotations

import os
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, field_validator

from .secrets import read_private, FinanceError


LOCAL_HTTP_NETWORKS = tuple(ip_network(network) for network in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "fc00::/7"))


class Settings(BaseModel):
    project_dir: Path
    application_id: str
    key_file: Path
    environment: Literal["production", "sandbox"] = "production"
    callback_url: str = "https://invalid.example/callback"
    api_base: str = "https://api.enablebanking.com"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8765

    @field_validator("application_id")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        return str(UUID(value.strip()))

    @field_validator("callback_url")
    @classmethod
    def valid_callback(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme not in {"https", "http"} or not url.netloc or not url.hostname
                or not url.path.startswith("/") or url.query or url.fragment
                or url.username or url.password):
            raise ValueError("callback URL must be a plain HTTP or HTTPS URL")
        try:
            url.port
        except ValueError:
            raise ValueError("callback URL has an invalid port") from None
        if url.scheme == "http" and url.hostname != "localhost":
            try:
                host_ip = ip_address(url.hostname)
            except ValueError:
                raise ValueError("HTTP callback must use localhost or a private IP address") from None
            if not any(host_ip in network for network in LOCAL_HTTP_NETWORKS):
                raise ValueError("HTTP callback must use localhost or a private IP address")
        return value

    @property
    def secrets_dir(self) -> Path:
        return self.project_dir / "secrets" / self.environment

    @classmethod
    def load(cls, environment: Literal["production", "sandbox"] = "production",
             *, allow_unconfigured: bool = False) -> "Settings":
        project = Path(os.environ.get("FAMILY_FINANCE_DIR", Path(__file__).resolve().parents[2])).resolve()
        secrets = project / "secrets" / environment
        app_file = secrets / "application_id"
        app_id = (read_private(app_file).decode("utf-8").strip() if app_file.exists() else
                  "00000000-0000-0000-0000-000000000000" if allow_unconfigured else
                  read_private(app_file).decode("utf-8").strip())
        callback_file = secrets / "callback_url"
        callback = (read_private(callback_file).decode("utf-8").strip() if callback_file.exists()
                    else os.environ.get("FAMILY_FINANCE_CALLBACK_URL", "https://invalid.example/callback"))
        try:
            return cls(project_dir=project, application_id=app_id,
                       environment=environment, key_file=secrets / "enable_banking.pem",
                       callback_url=callback,
                       listen_host=os.environ.get("FAMILY_FINANCE_LISTEN_HOST", "127.0.0.1"),
                       listen_port=int(os.environ.get("FAMILY_FINANCE_LISTEN_PORT", "8765")))
        except ValueError as exc:
            raise FinanceError("Invalid local configuration") from exc
