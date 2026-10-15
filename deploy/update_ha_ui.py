"""Install the finance card UI into an existing Home Assistant configuration.

Run with permission to write the HA config directory. This updates only the
card's static files and its extra_module_url cache key; it never edits other
dashboards or secrets. Check the HA configuration and restart HA afterwards.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from build_ui import build

MODULE_URL = re.compile(r"(?m)^(\s*- /local/family-finance-card\.js\?v=)[^\s]+$")


def install(target: Path) -> str:
    config = target / "configuration.yaml"
    original = config.read_text()
    if len(MODULE_URL.findall(original)) != 1:
        raise ValueError("Expected exactly one family-finance-card.js extra_module_url")
    with TemporaryDirectory(prefix="family-finance-ui-") as temporary:
        staged = Path(temporary)
        entry_hash = build(staged)
        for source in staged.rglob("*.js"):
            destination = target / "www" / source.relative_to(staged)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_file = destination.with_name(destination.name + ".new")
            shutil.copyfile(source, temporary_file)
            temporary_file.chmod(0o644)
            temporary_file.replace(destination)

    updated = MODULE_URL.sub(lambda match: match.group(1) + entry_hash, original)
    if updated != original:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config.with_name(f"configuration.yaml.before-finance-ui-{timestamp}")
        shutil.copy2(config, backup)
        temporary_config = config.with_name("configuration.yaml.finance-ui-new")
        temporary_config.write_text(updated)
        temporary_config.chmod(config.stat().st_mode & 0o777)
        os.chown(temporary_config, config.stat().st_uid, config.stat().st_gid)
        temporary_config.replace(config)
    return entry_hash


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(f"Installed Family Finance UI version {install(args.target)}; check config and restart Home Assistant")
