from __future__ import annotations

import os
from pathlib import Path
import stat
from uuid import UUID


class FinanceError(Exception):
    """Safe error text; never contains bank response bodies or secrets."""


def uuid_text(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise FinanceError("Expected a UUID") from exc


def read_private(path: Path) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise FinanceError("Secret file must be regular with mode 600 or stricter")
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise FinanceError("Required local secret file is missing") from exc


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise FinanceError("Secrets directory must have mode 700 or stricter")
    if path.exists() and (not path.is_file() or path.stat().st_mode & 0o077):
        raise FinanceError("Existing secret file has unsafe permissions")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
