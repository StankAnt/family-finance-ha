"""Private list of authorized AIS sessions for one Enable Banking application."""

from __future__ import annotations

from .config import Settings
from .secrets import FinanceError, read_private, uuid_text, write_private


class AuthorizationRequired(FinanceError):
    """Stored bank consents need interactive renewal."""


def authorized_sessions(settings: Settings, client) -> list[dict]:
    result = []
    for session_id in session_ids(settings):
        session = client.request("GET", f"/sessions/{session_id}")
        if session.get("status") == "AUTHORIZED":
            result.append(session)
        elif session.get("status") not in {"CLOSED", "EXPIRED", "REVOKED"}:
            raise FinanceError("Bank session is not authorized")
    if not result:
        raise AuthorizationRequired("Bank authorization expired. Reconnect bank accounts in dashboard settings.")
    return result


def session_ids(settings: Settings) -> list[str]:
    legacy = settings.secrets_dir / "session_id"
    registry = settings.secrets_dir / "session_ids"
    values = []
    for path in (legacy, registry):
        if path.exists() or path.is_symlink():
            raw = read_private(path).decode("ascii")
            for line in raw.splitlines():
                value = uuid_text(line.strip())
                if value not in values:
                    values.append(value)
    if not values:
        raise FinanceError("No authorized bank session is stored")
    if len(values) > 20:
        raise FinanceError("Too many authorized bank sessions")
    return values


def record_session(settings: Settings, session_id: str) -> int:
    value = uuid_text(session_id)
    legacy = settings.secrets_dir / "session_id"
    registry = settings.secrets_dir / "session_ids"
    values = session_ids(settings) if legacy.exists() or registry.exists() else []
    if value not in values:
        if len(values) >= 20:
            raise FinanceError("Too many authorized bank sessions")
        values.append(value)
    if not legacy.exists():
        write_private(legacy, values[0] + "\n")
    write_private(registry, "\n".join(values) + "\n")
    return len(values)
