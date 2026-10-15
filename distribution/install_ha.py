"""Add the Family Finance dashboard to an existing Home Assistant config.

Supports a regular configuration.yaml with inline frontend/lovelace mappings.
It refuses ambiguous include-based layouts instead of rewriting them.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
from build_ui import build  # noqa: E402


def section(lines: list[str], name: str) -> tuple[int, int] | None:
    markers = [index for index, line in enumerate(lines) if line.rstrip() == f"{name}:"]
    if not markers:
        if any(line.startswith(f"{name}:") for line in lines):
            raise ValueError(f"{name} uses an unsupported inline or include form")
        return None
    if len(markers) != 1:
        raise ValueError(f"Duplicate {name} section")
    start = markers[0]
    end = next((index for index in range(start + 1, len(lines))
                if lines[index] and not lines[index][0].isspace() and not lines[index].startswith("#")), len(lines))
    return start, end


def with_dashboard(original: str, digest: str, notify_service: str, api_ip: str,
                   callback_port: int = 8765) -> str:
    lines = original.splitlines(keepends=True)
    if section(lines, "family_finance") or "family-finance-dashboard.yaml" in original:
        raise ValueError("Family Finance already configured; use deploy/update_ha_ui.py to update")
    card_url = f"/local/family-finance-card.js?v={digest}"
    frontend = section(lines, "frontend")
    if frontend:
        start, end = frontend
        block = "".join(lines[start:end])
        if "extra_module_url:" in block:
            key_index = next((i for i in range(start + 1, end)
                              if lines[i].startswith("  extra_module_url:")), None)
            if key_index is None or lines[key_index].strip() != "extra_module_url:":
                raise ValueError("Unsupported frontend extra_module_url layout")
            insert = key_index + 1
            while insert < end and (lines[insert].startswith("    - ") or not lines[insert].strip()):
                insert += 1
            lines.insert(insert, f"    - {card_url}\n")
        else:
            lines.insert(end, f"  extra_module_url:\n    - {card_url}\n")
    else:
        lines.extend(["\n", "frontend:\n", f"  extra_module_url:\n    - {card_url}\n"])

    lovelace = section(lines, "lovelace")
    dashboard = ("    family-finance:\n"
                 "      mode: yaml\n"
                 "      title: Семейные финансы\n"
                 "      icon: mdi:finance\n"
                 "      show_in_sidebar: true\n"
                 "      require_admin: true\n"
                 "      filename: family-finance-dashboard.yaml\n")
    if lovelace:
        start, end = lovelace
        dashboards = next((i for i in range(start + 1, end)
                           if lines[i].startswith("  dashboards:")), None)
        if dashboards is None:
            lines.insert(end, "  dashboards:\n" + dashboard)
        elif lines[dashboards].strip() == "dashboards:":
            lines.insert(end, dashboard)
        else:
            raise ValueError("Unsupported lovelace dashboards layout")
    else:
        lines.extend(["\n", "lovelace:\n", "  dashboards:\n", dashboard])
    service_line = f"  notify_service: {notify_service}\n" if notify_service else ""
    lines.extend(["\n", "family_finance:\n",
                  "  key_path: /config/family_finance_key\n",
                  f"  api_url: http://{api_ip}:8766/api\n",
                  f"  callback_base_url: http://127.0.0.1:{callback_port}\n",
                  "  scheduled_sync: true\n",
                  service_line])
    return "".join(lines)


def install(config_dir: Path, notify_service: str = "") -> str:
    if notify_service and (not notify_service.replace("_", "").isalnum() or len(notify_service) > 100):
        raise ValueError("Invalid notification service name")
    config = config_dir / "configuration.yaml"
    env_file = ROOT / ".env"
    if not env_file.is_file():
        raise ValueError("Run distribution/bootstrap.py first")
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)
    try:
        subnet = ipaddress.ip_network(values["FINANCE_PRIVATE_SUBNET"], strict=True)
        api_ip = ipaddress.ip_address(values["FINANCE_API_IP"])
        callback_port = int(values["FINANCE_CALLBACK_PORT"])
    except (KeyError, ValueError):
        raise ValueError("Invalid private API network in .env") from None
    if api_ip not in subnet or api_ip.version != 4 or not 1024 <= callback_port <= 65535:
        raise ValueError("Private API address is outside its Docker subnet")
    try:
        with socket.create_connection((str(api_ip), 8766), timeout=3):
            pass
    except OSError:
        raise ValueError("Private API is not reachable from the HA host; start Compose services first") from None
    try:
        with socket.create_connection(("127.0.0.1", callback_port), timeout=3):
            pass
    except OSError:
        raise ValueError("Callback service is not reachable from the HA host; start Compose services first") from None
    key = ROOT / "secrets" / "dashboard_api_key"
    if not config.is_file() or not key.is_file():
        raise ValueError("Home Assistant configuration or bootstrapped API key is missing")
    if (config_dir / "family_finance_key").exists():
        raise ValueError("Home Assistant finance key already exists")
    with TemporaryDirectory(prefix="family-finance-build-") as temporary:
        staged = Path(temporary)
        digest = build(staged)
        updated = with_dashboard(config.read_text(), digest, notify_service, str(api_ip), callback_port)
        backup = config.with_name("configuration.yaml.before-family-finance-" +
                                  datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        shutil.copy2(config, backup)
        for source in staged.rglob("*.js"):
            destination = config_dir / "www" / source.relative_to(staged)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        component = config_dir / "custom_components" / "family_finance"
        component.mkdir(parents=True, exist_ok=True)
        for name in ("__init__.py", "manifest.json", "request_body.py"):
            shutil.copy2(ROOT / "deploy" / "ha_custom_components" / "family_finance" / name,
                         component / name)
        shutil.copy2(ROOT / "deploy" / "family-finance-dashboard.yaml",
                     config_dir / "family-finance-dashboard.yaml")
        key_copy = config_dir / "family_finance_key"
        fd = os.open(key_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(key.read_bytes())
        staged_config = config.with_name(config.name + ".family-finance-new")
        staged_config.write_text(updated)
        staged_config.chmod(config.stat().st_mode & 0o777)
        staged_config.replace(config)
        return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--notify-service", default="")
    args = parser.parse_args()
    print(f"Installed dashboard version {install(args.config_dir, args.notify_service)}. Check configuration and restart Home Assistant.")
