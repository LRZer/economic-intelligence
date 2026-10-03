"""Rate-limited historical backfill of selected Ministry of Finance releases."""

from __future__ import annotations

import argparse
from collections import Counter

from .app import connect, initialize, now, record_run, save_rows
from .fiscal import collect_fiscal


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill official national fiscal series")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--reparse", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.pages <= 9 or not 2000 <= args.start_year <= 2100:
        parser.error("pages or start-year outside supported bounds")
    initialize()
    started = now()
    with connect() as db:
        skip_urls = set() if args.reparse else {row[0] for row in db.execute(
            "SELECT DISTINCT source_url FROM observations WHERE source_url LIKE 'https://gks.mof.gov.cn/tongjishuju/%'")}
    rows, errors = collect_fiscal(pages=args.pages, recent_limit=None,
                                  skip_urls=skip_urls, start_year=args.start_year)
    if errors and not args.allow_partial:
        with connect() as db:
            record_run(db, started, "fiscal_backfill", "rejected", len(rows), 0, errors)
        raise SystemExit(f"Fiscal backfill had {len(errors)} source errors; database unchanged. "
                         + "; ".join(errors[:3]))
    if not rows:
        print("No new fiscal observations; database unchanged.")
        return
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, rows, now())
        after = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_fiscal_backfill', ?)", (now(),))
        record_run(db, started, "fiscal_backfill", "partial" if errors else "complete",
                   len(rows), after-before, errors)
    periods = [row["period"] for row in rows]
    print(f"Parsed {len(rows)} fiscal records; added {after-before}; periods {min(periods)} to {max(periods)}")
    print("Indicators:", dict(Counter(row["key"] for row in rows)))
    print("Source warnings:", len(errors))
    for error in errors[:10]:
        print(" -", error)


if __name__ == "__main__":
    main()
