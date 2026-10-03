"""Historical PBC backfill with raw evidence and an offline replay option."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

from .app import connect, initialize, now, record_run, save_rows
from .collector import fetch
from .finance import (SNAPSHOT_ROOT, discover_reports, discover_tables, fetch_table,
                     replay_snapshot, save_snapshot)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill selected official PBC monthly series")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--through-year", type=int, default=2026)
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--offline", type=Path, help="Replay a directory of pbc-*.json and matching HTML")
    parser.add_argument("--preview", action="store_true", help="Validate sources and show counts without database writes")
    args = parser.parse_args()
    if not (2015 <= args.start_year <= args.through_year <= 2100 and 1 <= args.pages <= 120):
        parser.error("Year range or page limit outside supported bounds")
    started = now()
    sources = []
    session = requests.Session()
    if args.offline:
        for path in sorted(args.offline.glob("pbc-*.json")):
            source = json.loads(path.read_text(encoding="utf-8"))
            raw = (args.offline / source["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ValueError(f"Source digest mismatch: {path.name}")
            sources.append((source, raw))
    else:
        reports = discover_reports(session, args.start_year, args.through_year, args.pages)
        tables = discover_tables(session, args.start_year, args.through_year)
        for source in [{**item, "kind": "financial_report"} for item in reports] + tables:
            _, raw = (fetch(session, source["source_url"], include_raw=True)
                      if source["kind"] == "financial_report" else fetch_table(session, source["source_url"]))
            sources.append((source, raw))
            time.sleep(0.4)
    if not sources:
        raise ValueError("No selected PBC source snapshots or reports found")
    # Validate the whole batch before any data or snapshots are written.
    sources.sort(key=lambda item: (item[0]["kind"] != "financial_report",
                                   item[0].get("published", ""), item[0]["source_url"]))
    parsed = [(source, raw, replay_snapshot(raw, source)) for source, raw in sources]
    rows = {}
    for source, raw, readings in parsed:
        if not readings:
            raise ValueError(f"No selected readings in {source['source_title']}")
        for row in readings:
            if args.start_year <= int(row["period"][:4]) <= args.through_year:
                identity = row["key"], row["period"]
                # Annual TSF tables can contain later official revisions. They
                # follow reports, and revisions remain in observation_changes.
                rows[identity] = row
    counts = {}
    for key, _ in rows:
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"sources": len(parsed), "parsed": len(rows), "by_indicator": counts,
                      "preview": args.preview}, ensure_ascii=False))
    if args.preview:
        return
    initialize()
    for source, raw, readings in parsed:
        save_snapshot(raw, source, readings)
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, list(rows.values()), started)
        after = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        record_run(db, started, "pbc_backfill", "complete", len(rows), after - before, [])
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_refresh', ?)", (started,))
    print(f"Added {after-before} official observations; total {after}")


if __name__ == "__main__":
    main()
