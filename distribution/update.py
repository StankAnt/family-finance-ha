"""Upgrade an installed Family Finance instance from the current source tree.

Run this after checking out a tagged release. Local secrets, .env, and the
Postgres volume are not replaced. Home Assistant remains on the old version if
the database migration or container rebuild fails.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "distribution" / "compose.yaml"


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def compose(*arguments: str) -> None:
    run("docker", "compose", "--env-file", ".env", "-f", str(COMPOSE), *arguments)


def update(config_dir: Path, ha_container: str | None = None) -> None:
    config_dir = config_dir.resolve()
    if not (ROOT / ".env").is_file() or not (ROOT / "secrets" / "dashboard_api_key").is_file():
        raise ValueError("This checkout has not been bootstrapped; stop before updating")
    if not (config_dir / "configuration.yaml").is_file():
        raise ValueError("Home Assistant configuration.yaml was not found")
    if not (config_dir / "family_finance_key").is_file():
        raise ValueError("Family Finance has not been installed in this Home Assistant")
    component = config_dir / "custom_components" / "family_finance"
    if not component.is_dir():
        raise ValueError("Home Assistant finance integration directory is missing")
    # Validate the card update before migrations or API replacement.
    card_urls = re.findall(r"(?m)^\s*- /local/family-finance-card\.js\?v=[^\s]+$",
                           (config_dir / "configuration.yaml").read_text())
    if len(card_urls) != 1:
        raise ValueError("Expected exactly one Family Finance card URL in Home Assistant configuration")

    # Build first, so a build failure cannot leave the old API running with a
    # partly updated Home Assistant card. Alembic migrations are repeatable.
    compose("build", "migrate", "api", "callback")
    compose("up", "-d", "db")
    compose("run", "--rm", "migrate")
    compose("up", "-d", "--no-build", "api", "callback")

    # The card updater stages content-hashed modules and updates only its own
    # module URL in configuration.yaml, keeping other HA settings intact.
    run("python3", "deploy/update_ha_ui.py", "--target", str(config_dir))
    for name in ("__init__.py", "manifest.json", "request_body.py"):
        source = ROOT / "deploy" / "ha_custom_components" / "family_finance" / name
        destination = component / name
        staged = destination.with_name(destination.name + ".new")
        shutil.copy2(source, staged)
        staged.replace(destination)

    if ha_container:
        run("docker", "exec", ha_container, "python", "-m", "homeassistant",
            "--script", "check_config", "-c", "/config")
        run("docker", "restart", ha_container)
        print("Family Finance updated; Home Assistant configuration checked and container restarted.")
    else:
        print("Family Finance updated. Check the Home Assistant configuration and restart it to load the integration.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True,
                        help="Host path of the Home Assistant configuration directory")
    parser.add_argument("--ha-container", help="HA container name; when set, check configuration and restart it")
    arguments = parser.parse_args()
    update(arguments.config_dir, arguments.ha_container)
