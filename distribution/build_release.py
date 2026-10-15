"""Build a curated source archive with no private instance files."""

from __future__ import annotations

import argparse
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = ("Dockerfile", "pyproject.toml", "alembic.ini", "LICENSE", ".dockerignore", ".gitignore")
TREES = ("src/family_finance", "migrations", "deploy/family-finance-ui",
         "deploy/ha_custom_components/family_finance", "distribution")
DEPLOY_FILES = ("deploy/family-finance-card.js", "deploy/family-finance-dashboard.yaml",
                "deploy/build_ui.py", "deploy/update_ha_ui.py")


def build(output: Path) -> None:
    files = [ROOT / name for name in (*TOP_LEVEL, *DEPLOY_FILES)]
    files.extend(path for tree in TREES for path in (ROOT / tree).rglob("*")
                 if path.is_file() and path.suffix in {".py", ".js", ".json", ".yaml", ".md"})
    with tarfile.open(output, "w:gz") as archive:
        for path in sorted(set(files)):
            relative = path.relative_to(ROOT)
            if relative == Path("distribution/README.md"):
                archive.add(path, arcname="family-finance/README.md")
            else:
                archive.add(path, arcname=Path("family-finance") / relative)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output)
    print(f"Archive created: {args.output}")
