from __future__ import annotations

import argparse
import sys

from .auth import AuthorizationService
from .config import Settings
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Enable Banking AIS management")
    parser.add_argument("--env", choices=("production", "sandbox"), default="production",
                        help="Isolated application profile (default: production)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("app")
    sub.add_parser("banks")
    auth = sub.add_parser("start-auth")
    auth.add_argument("--bank-name", required=True)
    sub.add_parser("complete-auth", help="Exchange code and state from private local files")
    sub.add_parser("session")
    diagnostics = sub.add_parser("inspect")
    diagnostics.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env)
        client = EnableBankingClient(settings)
        try:
            if args.command == "app":
                app = client.request("GET", "/application")
                if app.get("environment") != settings.environment.upper():
                    raise FinanceError("Application environment does not match selected profile")
                print(f"Application: environment={app.get('environment', 'unknown')}, active={app.get('active', 'unknown')}, AIS={'AIS' in app.get('services', [])}")
            elif args.command == "banks":
                verify_environment(client, settings)
                banks = client.request("GET", "/aspsps", params={"country": "PL"}).get("aspsps", [])
                for bank in banks:
                    name = bank.get("name", "") if isinstance(bank, dict) else ""
                    if "erste" in name.lower() or "santander" in name.lower():
                        print(name)
            elif args.command == "start-auth":
                path = AuthorizationService(settings, client).start(args.bank_name)
                print(f"Authorization URL saved locally to {path}")
            elif args.command == "complete-auth":
                count = AuthorizationService(settings, client).complete_from_files()
                print(f"{settings.environment.capitalize()} session saved; authorized accounts: {count}")
            elif args.command == "inspect":
                verify_environment(client, settings)
                from .reader import inspect
                from .secrets import uuid_text
                session_id = uuid_text(read_private(settings.secrets_dir / "session_id").decode().strip())
                for line in inspect(client, session_id, args.days):
                    print(line)
            elif args.command == "session":
                verify_environment(client, settings)
                from .secrets import uuid_text
                session_id = uuid_text(read_private(settings.secrets_dir / "session_id").decode().strip())
                result = client.request("GET", f"/sessions/{session_id}")
                print(f"Session: status={result.get('status', 'unknown')}; authorized accounts={len(result.get('accounts', []))}")
        finally:
            client.close()
        return 0
    except (FinanceError, OSError, UnicodeError) as exc:
        print(f"Error: {exc if isinstance(exc, FinanceError) else 'local file operation failed'}", file=sys.stderr)
        return 1


def verify_environment(client: EnableBankingClient, settings: Settings) -> None:
    app = client.request("GET", "/application")
    if app.get("environment") != settings.environment.upper():
        raise FinanceError("Application environment does not match selected profile")


if __name__ == "__main__":
    raise SystemExit(main())
