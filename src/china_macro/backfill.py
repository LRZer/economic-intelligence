"""One-time, rate-limited historical NBS release backfill.

Examples:
  python backfill.py --start-year 2024 --pages 50
  python backfill.py --archive main --start-year 2021 --through-year 2023 --pages 67
"""

from __future__ import annotations

import argparse
from collections import Counter

from .app import connect, initialize, now, record_run, save_rows
from .collector import collect


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill selected official NBS monthly releases")
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--through-year", type=int, default=None)
    parser.add_argument("--archive", choices=("disclosure", "main"), default="disclosure")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--allow-partial", action="store_true", help="Commit parsed records even when some official pages fail")
    parser.add_argument("--reparse", action="store_true", help="Read source articles already represented in the database")
    args = parser.parse_args()
    args.pages = args.pages or (67 if args.archive == "main" else 50)
    if (not 2015 <= args.start_year <= 2100 or not 1 <= args.pages <= 120
            or (args.through_year is not None and not args.start_year <= args.through_year <= 2100)):
        parser.error("start-year, through-year or pages outside supported bounds")
    initialize()
    started = now()
    with connect() as db:
        source_path = ("/sj/zxfb/%" if args.archive == "main" else "/xxgk/sjfb/zxfb2020/%")
        skip_urls = set() if args.reparse else {row[0] for row in db.execute(
            "SELECT DISTINCT source_url FROM observations WHERE source_url LIKE ?",
            ("https://www.stats.gov.cn" + source_path,),
        )}
    rows, errors = collect(nbs_pages=args.pages, start_year=args.start_year,
                           through_year=args.through_year, nbs_archive=args.archive,
                           include_pbc=False, include_trade=False, include_fiscal=False,
                           include_cny=False,
                           skip_urls=skip_urls)
    if not rows:
        with connect() as db:
            record_run(db, started, "backfill", "failed", 0, 0,
                       errors or ["No new official observations parsed"])
        raise SystemExit("No new official observations parsed; database was not changed. " + "; ".join(errors[:3]))
    if errors and not args.allow_partial:
        with connect() as db:
            record_run(db, started, "backfill", "rejected", len(rows), 0, errors)
        raise SystemExit(f"Backfill incomplete ({len(errors)} source errors); database was not changed. "
                         + "; ".join(errors[:3]))
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, rows, now())
        after = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_backfill', ?)", (now(),))
        record_run(db, started, "backfill", "partial" if errors else "complete",
                   len(rows), after-before, errors)
    periods = [row["period"] for row in rows]
    print(f"Parsed {len(rows)} records, added {after-before}; source periods {min(periods)} to {max(periods)}")
    print("Indicator counts:", dict(Counter(row["key"] for row in rows)))
    print(f"Fetch warnings: {len(errors)}")
    for warning in errors[:10]:
        print(" -", warning)


if __name__ == "__main__":
    main()
