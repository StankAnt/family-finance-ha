"""Manual local accounting commands. Outputs contain aggregates only."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from sqlalchemy.orm import Session

from .accounting import import_manual, monthly_report, position_report, sync_nbp
from .secrets import FinanceError, read_private
from .sync import database_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("fx-sync", "month", "position", "manual-import"))
    parser.add_argument("--from-date", type=date.fromisoformat)
    parser.add_argument("--to-date", type=date.fromisoformat)
    parser.add_argument("--period", help="YYYY-MM")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    try:
        engine = database_engine(Path("secrets/database_url"))
        with Session(engine) as db:
            if args.command == "fx-sync":
                if not args.from_date or not args.to_date:
                    raise FinanceError("fx-sync requires --from-date and --to-date")
                count = sync_nbp(db, args.from_date, args.to_date)
                db.commit()
                print(json.dumps({"rates_added": count}))
            elif args.command == "month":
                if not args.period or len(args.period) != 7 or args.period[4] != "-":
                    raise FinanceError("month requires --period YYYY-MM")
                print(json.dumps(monthly_report(db, int(args.period[:4]), int(args.period[5:])),
                                 ensure_ascii=False, indent=2))
            elif args.command == "position":
                if args.as_of is None:
                    raise FinanceError("position requires --as-of")
                print(json.dumps(position_report(db, args.as_of), ensure_ascii=False, indent=2))
            else:
                if args.file is None:
                    raise FinanceError("manual-import requires --file")
                payload = json.loads(read_private(args.file))
                if not isinstance(payload, dict):
                    raise FinanceError("Manual file must contain an object")
                counts = import_manual(db, payload)
                db.commit()
                print(json.dumps({"imported": counts}))
    except (FinanceError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Accounting error: {exc if isinstance(exc, FinanceError) else 'invalid input'}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
