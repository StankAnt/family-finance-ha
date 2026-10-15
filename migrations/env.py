from __future__ import annotations

import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from family_finance.models import Base
from family_finance.secrets import read_private

target_metadata = Base.metadata


def database_url() -> str:
    test_url = os.environ.get("FAMILY_FINANCE_MIGRATION_TEST_URL")
    if test_url:
        return test_url
    path = Path(os.environ.get("FAMILY_FINANCE_DATABASE_URL_FILE", "secrets/database_url"))
    url = read_private(path).decode("utf-8").strip()
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Migrations require a private PostgreSQL URL")
    return url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata,
                              compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
