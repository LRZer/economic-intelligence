"""Idempotent historical import of MOFCOM's GACC-sourced USD trade table."""

from __future__ import annotations

import argparse

from .app import connect, initialize, now, record_run, save_rows
from .trade import collect_trade


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill selected USD trade series")
    parser.add_argument("--start", default="202101", help="First month as YYYYMM")
    parser.add_argument("--end", default=None, help="Last month as YYYYMM; defaults to current month")
    args = parser.parse_args()
    initialize()
    started = now()
    try:
        rows, manifest = collect_trade(args.start, args.end)
        with connect() as db:
            before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            save_rows(db, rows, now())
            added = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] - before
            record_run(db, started, "trade_backfill", "complete", len(rows), added, [])
        periods = {row["period"] for row in rows}
        print(f"Imported {len(rows)} observations across {len(periods)} months; added {added}.")
        print(f"Source response SHA-256: {manifest['sha256']}")
        print(f"Raw source snapshot: {manifest['path']}")
    except Exception as exc:
        with connect() as db:
            record_run(db, started, "trade_backfill", "failed", 0, 0,
                       [f"{type(exc).__name__}: {exc}"])
        raise


if __name__ == "__main__":
    main()
