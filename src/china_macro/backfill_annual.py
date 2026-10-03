"""Revisit selected NBS year-end releases without re-fetching monthly articles."""

from __future__ import annotations

import argparse
import re
import time

import requests

from .app import connect, initialize, now, record_run, save_rows
from .collector import fetch, nbs_links, parse_nbs_special


def is_annual(title: str, kind: str, period: str) -> bool:
    return (kind in {"investment", "estate", "profit"} and period.endswith("-12")
            and bool(re.match(r"20\d{2}年(?:全国)?(?:固定资产投资|房地产市场|房地产开发投资|规模以上工业企业利润)", title)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill selected NBS annual cumulative releases")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--year", type=int, choices=range(2021, 2026),
                        help="Reparse one annual reporting year")
    args = parser.parse_args()
    initialize()
    started = now()
    session = requests.Session()
    errors: list[str] = []
    links = []
    for archive, first, last, pages in (("main", 2021, 2023, 67),
                                         ("disclosure", 2024, 2025, 50)):
        if args.year and not first <= args.year <= last:
            continue
        links.extend(link for link in nbs_links(session, pages=pages,
                                                start_year=args.year or first,
                                                through_year=args.year or last,
                                                archive=archive, errors=errors)
                     if is_annual(link[1], link[2], link[3]))
    rows = []
    for url, title, kind, period, published in links:
        try:
            rows.extend(parse_nbs_special(fetch(session, url), url, title, kind, period, published))
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            errors.append(f"{title[:24]}: {type(exc).__name__}")
        time.sleep(0.4)
    if not rows or (errors and not args.allow_partial):
        with connect() as db:
            record_run(db, started, "annual_backfill", "rejected" if rows else "failed",
                       len(rows), 0, errors or ["No annual observations parsed"])
        raise SystemExit(f"Annual backfill not committed: {len(rows)} parsed, {len(errors)} source errors")
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, rows, now())
        added = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] - before
        record_run(db, started, "annual_backfill", "partial" if errors else "complete",
                   len(rows), added, errors)
    print(f"Selected {len(links)} annual reports; parsed {len(rows)} observations; added {added}; source errors {len(errors)}")


if __name__ == "__main__":
    main()
