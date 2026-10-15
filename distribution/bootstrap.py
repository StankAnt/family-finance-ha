"""Create local credentials for a fresh installation without printing them."""

from __future__ import annotations

import os
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import subprocess
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def _occupied_networks() -> list[ipaddress.IPv4Network]:
    occupied = []
    try:
        routes = subprocess.run(["ip", "-j", "route", "show"], capture_output=True, text=True, check=False)
        known_routes = json.loads(routes.stdout) if routes.returncode == 0 else []
    except (FileNotFoundError, ValueError):
        known_routes = []
    for route in known_routes:
        destination = route.get("dst")
        if destination and destination != "default":
            try:
                occupied.append(ipaddress.IPv4Network(destination, strict=False))
            except ValueError:
                pass
    networks = subprocess.run(["docker", "network", "ls", "-q"],
                              capture_output=True, text=True, check=True).stdout.split()
    if networks:
        details = subprocess.run(["docker", "network", "inspect", *networks],
                                 capture_output=True, text=True, check=True)
        for network in json.loads(details.stdout):
            for config in network.get("IPAM", {}).get("Config", []) or []:
                subnet = config.get("Subnet")
                if subnet:
                    try:
                        occupied.append(ipaddress.IPv4Network(subnet, strict=False))
                    except ValueError:
                        pass
    return occupied


def _private_network() -> tuple[str, str]:
    occupied = _occupied_networks()
    candidates = [(major, minor) for major in range(24, 32) for minor in range(20, 240)]
    for major, minor in secrets.SystemRandom().sample(candidates, len(candidates)):
        subnet = ipaddress.IPv4Network(f"172.{major}.{minor}.0/24")
        if not any(subnet.overlaps(existing) for existing in occupied):
            # Docker gives the first dynamic addresses to db and one-off migrate.
            return str(subnet), str(subnet.network_address + 200)
    raise RuntimeError("No unused Docker private subnet found")


def _callback_port() -> int:
    candidates = [8765, *secrets.SystemRandom().sample(range(20000, 50000), 100)]
    for port in candidates:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free callback port found")


def write_new(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)


def bootstrap(root: Path = ROOT) -> None:
    secret_dir = root / "secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_dir.chmod(0o700)
    (secret_dir / "production").mkdir(mode=0o700, exist_ok=True)
    (secret_dir / "production").chmod(0o700)
    (secret_dir / "openai").mkdir(mode=0o700, exist_ok=True)
    (secret_dir / "openai").chmod(0o700)
    write_new(secret_dir / "db_password", secrets.token_urlsafe(36) + "\n")
    password = (secret_dir / "db_password").read_text().strip()
    url = f"postgresql+psycopg://finance:{quote(password, safe='')}@db:5432/family_finance\n"
    for name in ("database_url", "production_database_url", "production_database_url_host"):
        write_new(secret_dir / name, url)
    write_new(secret_dir / "dashboard_api_key", secrets.token_urlsafe(48) + "\n")
    if not (root / ".env").exists():
        subnet, api_ip = _private_network()
        callback_port = _callback_port()
        write_new(root / ".env", f"FINANCE_UID={os.getuid()}\nFINANCE_GID={os.getgid()}\n"
                  f"FINANCE_PRIVATE_SUBNET={subnet}\nFINANCE_API_IP={api_ip}\n"
                  f"FINANCE_CALLBACK_PORT={callback_port}\n")


if __name__ == "__main__":
    bootstrap()
    print("Local credentials created. Continue with the installation guide.")
