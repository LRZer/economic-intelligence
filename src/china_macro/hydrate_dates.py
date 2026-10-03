"""Fill missing publication dates from the official NBS directory metadata.

Article URLs in the older archive sometimes contain a site-migration date,
so only the directory's displayed release date is used here.
"""

from __future__ import annotations

import argparse

import requests

from .app import connect, initialize, now, record_run
from .collector import nbs_links


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill missing NBS publication dates from official directory pages")
    parser.add_argument("--archive", choices=("disclosure", "main"), default="disclosure")
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--through-year", type=int)
    parser.add_argument("--pages", type=int)
    args = parser.parse_args()
    pages = args.pages or (67 if args.archive == "main" else 50)
    if not 2015 <= args.start_year <= 2100 or not 1 <= pages <= 120:
        parser.error("start-year or pages outside supported bounds")
    initialize()
    started = now()
    errors: list[str] = []
    links = nbs_links(requests.Session(), pages=pages, start_year=args.start_year,
                      through_year=args.through_year, archive=args.archive, errors=errors)
    dated = [(url, published) for url, _, _, _, published in links if published]
    with connect() as db:
        changed = 0
        for url, published in dated:
            changed += db.execute(
                "UPDATE observations SET published=? WHERE source_url=? AND published=''",
                (published, url),
            ).rowcount
        status = "failed" if not links else "partial" if errors else "complete"
        record_run(db, started, "date_hydration", status, len(links), changed,
                   errors or (["No selected official reports found"] if not links else []))
    print(f"Directory reports: {len(links)}; dated reports: {len(dated)}; observations updated: {changed}")
    for warning in errors[:5]:
        print(" -", warning)


if __name__ == "__main__":
    main()
