"""Invoke the loopback background AIS sync without browser or PSU identity."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from .secrets import read_private


def main() -> None:
    project = Path(os.environ.get("FAMILY_FINANCE_DIR", Path(__file__).resolve().parents[2]))
    key = read_private(project / "secrets" / "dashboard_api_key").decode().strip()
    callback_base = os.environ.get("FAMILY_FINANCE_CALLBACK_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    response = httpx.post(f"{callback_base}/internal/sync-background",
                          headers={"X-Finance-Key": key}, timeout=900)
    response.raise_for_status()
    result = response.json()
    print("Bank sync skipped: recent run" if result.get("skipped") else
          "Bank sync completed")


if __name__ == "__main__":
    main()
