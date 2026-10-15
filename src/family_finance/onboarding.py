"""Local, admin-only Enable Banking setup and copy/paste authorization flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .auth import AuthorizationService
from .config import Settings
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private, write_private


def _certificate(key: rsa.RSAPrivateKey) -> str:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Family Finance Enable Banking")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=1))
                   .not_valid_after(now + timedelta(days=3650))
                   .sign(key, hashes.SHA256()))
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _private_key(pem: str) -> rsa.RSAPrivateKey:
    if not isinstance(pem, str) or not 1000 <= len(pem) <= 16000:
        raise FinanceError("Invalid RSA private key")
    try:
        key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeError):
        raise FinanceError("Invalid RSA private key") from None
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise FinanceError("RSA key must be at least 2048 bits")
    return key


def _callback(value: str) -> str:
    host = urlsplit(value).hostname or ""
    if host == "example.com" or host.endswith(".example"):
        raise FinanceError("Use your own Home Assistant HTTPS address as the redirect URL")
    try:
        validated = Settings(project_dir=Path("."), application_id=str(UUID(int=0)),
                             key_file=Path("key"), callback_url=value)
    except (ValueError, TypeError):
        raise FinanceError("Enter a plain HTTPS redirect URL") from None
    return validated.callback_url


def status(project_dir: Path) -> dict:
    directory = project_dir / "secrets" / "production"
    callback_file = directory / "callback_url"
    cert_file = directory / "public.crt"
    return {
        "has_key": (directory / "enable_banking.pem").exists(),
        "has_application_id": (directory / "application_id").exists(),
        "has_session": (directory / "session_ids").exists() or (directory / "session_id").exists(),
        "callback_url": (read_private(callback_file).decode().strip() if callback_file.exists()
                         else ""),
        "has_certificate": cert_file.exists() or (directory / "enable_banking.pem").exists(),
        "has_openai_key": (project_dir / "secrets" / "openai" / "api_key").exists(),
        "ai_enabled": ai_enabled(project_dir),
    }


def ai_enabled(project_dir: Path) -> bool:
    path = project_dir / "secrets" / "openai" / "enabled"
    return path.exists() and read_private(path).decode("ascii").strip() == "1"


def configure(project_dir: Path, payload: dict) -> dict:
    if set(payload) - {"application_id", "private_key", "callback_url", "openai_api_key", "ai_enabled"}:
        raise FinanceError("Unexpected setup fields")
    directory = project_dir / "secrets" / "production"
    key_text = payload.get("private_key")
    app_id = payload.get("application_id")
    callback = payload.get("callback_url")
    openai_key = payload.get("openai_api_key")
    enabled = payload.get("ai_enabled")
    if app_id:
        try:
            app_id = str(UUID(app_id.strip()))
        except (ValueError, AttributeError):
            raise FinanceError("Invalid application UUID") from None
    if callback:
        callback = _callback(callback)
    if openai_key is not None and (not isinstance(openai_key, str) or
                                  not 20 <= len(openai_key) <= 500 or any(char.isspace() for char in openai_key)):
        raise FinanceError("Invalid OpenAI API key")
    if enabled is not None and not isinstance(enabled, bool):
        raise FinanceError("Invalid AI setting")
    if enabled and not (openai_key or (project_dir / "secrets" / "openai" / "api_key").exists()):
        raise FinanceError("Add an OpenAI API key before enabling classification")
    if key_text:
        key = _private_key(key_text)
        write_private(directory / "enable_banking.pem", key_text.strip() + "\n")
        write_private(directory / "public.crt", _certificate(key))
    if app_id:
        write_private(directory / "application_id", app_id + "\n")
    if callback:
        write_private(directory / "callback_url", callback + "\n")
    if openai_key:
        write_private(project_dir / "secrets" / "openai" / "api_key", openai_key + "\n")
    if enabled is not None:
        write_private(project_dir / "secrets" / "openai" / "enabled", "1\n" if enabled else "0\n")
    return status(project_dir)


def generate_keypair(project_dir: Path) -> dict:
    directory = project_dir / "secrets" / "production"
    if (directory / "enable_banking.pem").exists():
        raise FinanceError("RSA key already exists; upload a replacement explicitly")
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    private = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode("ascii")
    write_private(directory / "enable_banking.pem", private)
    write_private(directory / "public.crt", _certificate(key))
    return status(project_dir)


def public_certificate(project_dir: Path) -> dict:
    directory = project_dir / "secrets" / "production"
    certificate = directory / "public.crt"
    if not certificate.exists():
        pem = read_private(directory / "enable_banking.pem").decode("ascii")
        write_private(certificate, _certificate(_private_key(pem)))
    return {"certificate": read_private(certificate).decode("ascii")}


def start_authorization(project_dir: Path, payload: dict) -> dict:
    if set(payload) != {"bank_name"} or not isinstance(payload["bank_name"], str) or not 1 <= len(payload["bank_name"]) <= 120:
        raise FinanceError("Select a bank")
    settings = Settings.load("production")
    client = EnableBankingClient(settings)
    try:
        path = AuthorizationService(settings, client).start(payload["bank_name"].strip())
        return {"url": read_private(path).decode().strip(), "callback_url": settings.callback_url}
    finally:
        client.close()


def list_banks(project_dir: Path) -> dict:
    settings = Settings.load("production")
    client = EnableBankingClient(settings)
    try:
        app = client.request("GET", "/application")
        if app.get("environment") != "PRODUCTION":
            raise FinanceError("Application is not a production AIS application")
        banks = client.request("GET", "/aspsps", params={"country": "PL"}).get("aspsps", [])
        names = sorted({bank.get("name") for bank in banks if isinstance(bank, dict) and
                        bank.get("country") == "PL" and isinstance(bank.get("name"), str)})
        return {"banks": names}
    finally:
        client.close()


def complete_authorization(project_dir: Path, payload: dict) -> dict:
    if set(payload) != {"redirected_url"} or not isinstance(payload["redirected_url"], str) or len(payload["redirected_url"]) > 8192:
        raise FinanceError("Paste the final redirect URL")
    settings = Settings.load("production")
    expected, actual = urlsplit(settings.callback_url), urlsplit(payload["redirected_url"])
    if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
        raise FinanceError("Redirect URL does not match the configured callback")
    params = parse_qs(actual.query, keep_blank_values=True)
    if set(params) != {"code", "state"} or len(params["code"]) != 1 or len(params["state"]) != 1:
        raise FinanceError("Redirect URL must contain one code and one state")
    client = EnableBankingClient(settings)
    try:
        count = AuthorizationService(settings, client).complete(params["state"][0], params["code"][0])
        return {"authorized_accounts": count, "has_session": True}
    finally:
        client.close()
