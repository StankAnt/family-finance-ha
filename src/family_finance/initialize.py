"""Create the one-household ledger and generic categories after migrations."""

from __future__ import annotations

from pathlib import Path
import os

from sqlalchemy.orm import Session

from .classification import seed
from .sync import _household, database_engine


def main() -> None:
    project = Path(os.environ.get("FAMILY_FINANCE_DIR", Path(__file__).resolve().parents[2]))
    engine = database_engine(project / "secrets" / "production_database_url")
    try:
        with Session(engine) as db, db.begin():
            _household(db)
            seed(db)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
