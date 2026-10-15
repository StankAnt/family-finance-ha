"""Build cache-safe ES modules for the Home Assistant custom card.

Only relative imports inside deploy/ are accepted. Each imported module gets a
content hash in its URL; a change in any dependency changes the entry hash.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import re

SOURCE = Path(__file__).resolve().parent
ENTRY = Path("family-finance-card.js")
IMPORT = re.compile(r'(?P<before>\bfrom\s+["\'])(?P<path>\.[^"\'?]+\.js)(?:\?v=[^"\']*)?(?P<after>["\'])')


def build(output: Path) -> str:
    built: dict[Path, tuple[str, str]] = {}
    visiting: set[Path] = set()

    def module(relative: Path) -> tuple[str, str]:
        if relative in built:
            return built[relative]
        if relative in visiting:
            raise ValueError(f"Circular UI import: {relative}")
        source = (SOURCE / relative).resolve()
        if not source.is_relative_to(SOURCE) or not source.is_file():
            raise ValueError(f"UI import outside deploy/: {relative}")
        visiting.add(relative)

        def replace(match: re.Match[str]) -> str:
            dependency = (relative.parent / match.group("path")).as_posix()
            dependency_path = Path(dependency)
            _, digest = module(dependency_path)
            return f'{match.group("before")}{match.group("path")}?v={digest}{match.group("after")}'

        content = IMPORT.sub(replace, source.read_text())
        digest = sha256(content.encode()).hexdigest()[:12]
        visiting.remove(relative)
        built[relative] = content, digest
        return built[relative]

    _, entry_hash = module(ENTRY)
    for relative, (content, _) in built.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return entry_hash


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(build(args.output.resolve()))
