"""Read-only data integrity audit for the local macroeconomic database."""

from __future__ import annotations

from .paths import DATA_ROOT

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .app import connect, now
from .catalog import INDICATORS
from .collector import LIMITS
from .trade import PAGE_URL, parse_trade_payload
from .fiscal import parse_fiscal_html
from .nbs_gap import parse_target
from .finance import replay_snapshot as replay_finance_snapshot
from .cny_trade import parse_cny_payload
from .quality import coverage


ALLOWED_HOSTS = {"www.stats.gov.cn", "www.pbc.gov.cn", "data.mofcom.gov.cn", "gks.mof.gov.cn", "fdi.mofcom.gov.cn"}
SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"
BUNDLED_SNAPSHOT_ROOT = Path(__file__).resolve().parent / "bundled_snapshots"


def audit_observations(rows: list[dict]) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    dated = 0
    sources = set()
    publishers = Counter()
    for row in rows:
        identity = f"{row['key']} {row['period']}"
        key = row["key"]
        if key not in INDICATORS:
            errors.append(f"{identity}: unknown indicator")
        if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", row["period"]):
            errors.append(f"{identity}: invalid period")
        url = urlparse(row["source_url"])
        if url.scheme != "https" or url.hostname not in ALLOWED_HOSTS:
            errors.append(f"{identity}: source URL is not an allowlisted official host")
        sources.add(row["source_url"])
        publishers[url.hostname or "unknown"] += 1
        if not row["source_title"].strip():
            errors.append(f"{identity}: source title is empty")
        value = row["value"]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{identity}: value is not finite")
        elif key in LIMITS and not LIMITS[key][0] <= value <= LIMITS[key][1]:
            errors.append(f"{identity}: value outside indicator guardrail")
        if row["published"]:
            try:
                publication = date.fromisoformat(row["published"])
                dated += 1
                if re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", row["period"]):
                    period_year, period_month = map(int, row["period"].split("-"))
                    lag = (publication.year - period_year) * 12 + publication.month - period_month
                    if not 0 <= lag <= 3:
                        warnings.append(f"{identity}: publication lag is {lag} months")
            except ValueError:
                errors.append(f"{identity}: invalid publication date")
    return {
        "observation_count": len(rows), "source_count": len(sources),
        "dated_count": dated, "undated_count": len(rows) - dated,
        "publisher_counts": dict(publishers),
        "errors": errors, "warnings": warnings,
    }


def audit_trade_snapshots(root: Path, observations: list[dict],
                          fallback_root: Path | None = None) -> dict:
    errors: list[str] = []
    manifests = []
    meta_paths = set(root.glob("mofcom-trade-*.meta.json"))
    if fallback_root is not None:
        meta_paths.update(fallback_root.glob("mofcom-trade-*.meta.json"))
    for meta_path in sorted(meta_paths):
        raw_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".json")
        try:
            manifest = json.loads(meta_path.read_text(encoding="utf-8"))
            content = raw_path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if (manifest["sha256"] != digest or digest not in raw_path.name
                    or manifest["source_page"] != PAGE_URL):
                raise ValueError("snapshot digest or source does not match")
            start, end = manifest["requested_range"]
            parsed = parse_trade_payload(json.loads(content.decode("utf-8")), start, end)
            if (len(parsed) != manifest["observation_count"]
                    or min(row["period"] for row in parsed) != manifest["first_period"]
                    or max(row["period"] for row in parsed) != manifest["last_period"]):
                raise ValueError("snapshot record counts or periods do not match")
            manifests.append((manifest["fetched_at"], parsed))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{meta_path.name}: invalid source snapshot ({type(exc).__name__})")
    checked = 0
    if manifests:
        latest = max(manifests, key=lambda item: item[0])[1]
        actual = {(row["key"], row["period"]): row["value"] for row in observations}
        for row in latest:
            checked += 1
            if actual.get((row["key"], row["period"])) != row["value"]:
                errors.append(f"{row['key']} {row['period']}: differs from latest official source snapshot")
    return {"snapshot_count": len(manifests), "snapshot_checked_observations": checked,
            "snapshot_errors": errors}


def audit_fiscal_snapshots(root: Path, observations: list[dict],
                           fallback_root: Path | None = None) -> dict:
    errors: list[str] = []
    snapshots: dict[str, tuple[str, list[dict]]] = {}
    meta_paths = set(root.glob("mof-fiscal-*.meta.json"))
    if fallback_root is not None:
        meta_paths.update(fallback_root.glob("mof-fiscal-*.meta.json"))
    for meta_path in sorted(meta_paths):
        raw_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".html")
        try:
            manifest = json.loads(meta_path.read_text(encoding="utf-8"))
            content = raw_path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if manifest["sha256"] != digest or digest not in raw_path.name:
                raise ValueError("Fiscal snapshot digest does not match")
            parsed = parse_fiscal_html(content, manifest["source_url"], manifest["source_title"],
                                       manifest["period"], manifest["published"])
            if len(parsed) != manifest["observation_count"]:
                raise ValueError("Fiscal snapshot record count does not match")
            old = snapshots.get(manifest["source_url"])
            if old is None or old[0] < manifest["fetched_at"]:
                snapshots[manifest["source_url"]] = (manifest["fetched_at"], parsed)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{meta_path.name}: invalid fiscal source snapshot ({type(exc).__name__})")
    checked = 0
    for row in observations:
        if urlparse(row["source_url"]).hostname != "gks.mof.gov.cn":
            continue
        snapshot = snapshots.get(row["source_url"])
        if snapshot is None:
            errors.append(f"{row['key']} {row['period']}: missing fiscal source snapshot")
            continue
        expected = next((item for item in snapshot[1] if item["key"] == row["key"]
                         and item["period"] == row["period"]), None)
        checked += 1
        if expected is None or expected["value"] != row["value"]:
            errors.append(f"{row['key']} {row['period']}: differs from latest fiscal source snapshot")
    return {"fiscal_snapshot_count": len(snapshots),
            "fiscal_snapshot_checked_observations": checked, "fiscal_snapshot_errors": errors}


def audit_nbs_gap_snapshots(root: Path, observations: list[dict],
                            fallback_root: Path | None = None) -> dict:
    errors: list[str] = []
    snapshots: dict[tuple[str, str, str], tuple[str, float]] = {}
    paths = set(root.glob("nbs-gap-*.meta.json"))
    if fallback_root is not None:
        paths.update(fallback_root.glob("nbs-gap-*.meta.json"))
    valid = 0
    seen_snapshots: set[tuple[str, str]] = set()
    for meta_path in sorted(paths):
        try:
            manifest = json.loads(meta_path.read_text(encoding="utf-8"))
            raw_path = meta_path.with_name(f"nbs-gap-{manifest['sha256']}.html")
            content = raw_path.read_bytes()
            if (hashlib.sha256(content).hexdigest() != manifest["sha256"]
                    or not meta_path.name.startswith(f"nbs-gap-{manifest['sha256']}-")):
                raise ValueError("NBS snapshot digest does not match")
            parsed = parse_target(BeautifulSoup(content, "html.parser"), manifest,
                                  manifest["key"])
            if (parsed is None or parsed["value"] != manifest["value"]
                    or parsed["period"] != manifest["period"]):
                raise ValueError("NBS snapshot reparse differs from manifest")
            identity = (manifest["key"], manifest["period"], manifest["source_url"])
            if identity not in snapshots or snapshots[identity][0] < manifest["fetched_at"]:
                snapshots[identity] = (manifest["fetched_at"], parsed["value"])
            snapshot_identity = (manifest["sha256"], manifest["key"])
            if snapshot_identity not in seen_snapshots:
                valid += 1
                seen_snapshots.add(snapshot_identity)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{meta_path.name}: invalid NBS source snapshot ({type(exc).__name__})")
    actual = {(row["key"], row["period"]): row for row in observations}
    checked = 0
    for identity, (_, value) in snapshots.items():
        row = actual.get(identity[:2])
        if row is None or row["source_url"] != identity[2]:
            continue
        checked += 1
        if row["value"] != value:
            errors.append(f"{identity[0]} {identity[1]}: differs from NBS source snapshot")
    return {"nbs_gap_snapshot_count": valid,
            "nbs_gap_snapshot_checked_observations": checked,
            "nbs_gap_snapshot_errors": errors}


def audit_finance_snapshots(root: Path, observations: list[dict],
                            fallback_root: Path | None = None) -> dict:
    manifests = list(root.glob("pbc-*.json"))
    if fallback_root:
        manifests += list(fallback_root.glob("pbc-*.json"))
    snapshots, errors, valid = {}, [], set()
    for path in manifests:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if Path(meta["file"]).name != meta["file"]:
                raise ValueError("Snapshot filename must be local")
            raw = (path.parent / meta["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError("PBC source digest mismatch")
            parsed = replay_finance_snapshot(raw, meta)
            values = [{key: row[key] for key in ("key", "period", "value")} for row in parsed]
            if len(parsed) != meta["record_count"] or values != meta["rows"]:
                raise ValueError("PBC source replay differs from manifest")
            valid.add((meta["sha256"], meta["source_url"], meta["kind"]))
            for row in parsed:
                identity = row["key"], row["period"], row["source_url"]
                previous = snapshots.get(identity)
                if previous is None or previous[0] <= meta["fetched_at"]:
                    snapshots[identity] = meta["fetched_at"], row
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: invalid PBC source snapshot ({type(exc).__name__})")
    checked = 0
    for row in observations:
        if row["key"] not in {"m1_yoy", "m1_legacy_yoy", "m2_yoy", "tsf_stock_yoy", "loans_ytd"}:
            continue
        checked += 1
        candidate = snapshots.get((row["key"], row["period"], row["source_url"]))
        if candidate is None:
            errors.append(f"{row['key']} {row['period']}: missing PBC source snapshot")
        elif any(candidate[1][field] != row[field] for field in ("value", "published", "source_title")):
            errors.append(f"{row['key']} {row['period']}: differs from PBC source snapshot")
    return {"finance_snapshot_count": len(valid),
            "finance_snapshot_checked_observations": checked, "finance_snapshot_errors": errors}


def audit_cny_snapshots(root: Path, observations: list[dict],
                        fallback_root: Path | None = None) -> dict:
    manifests = list(root.glob("mofcom-cny-*.meta.json"))
    if fallback_root:
        manifests += list(fallback_root.glob("mofcom-cny-*.meta.json"))
    snapshots, errors, valid = {}, [], set()
    for path in manifests:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if Path(meta["file"]).name != meta["file"]:
                raise ValueError("Snapshot file must be local")
            raw = (path.parent / meta["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError("CNY source digest mismatch")
            parsed = parse_cny_payload(json.loads(raw), meta["source_url"])
            if len(parsed) != meta["record_count"]:
                raise ValueError("CNY snapshot count mismatch")
            valid.add((meta["sha256"], meta["source_url"]))
            for row in parsed:
                identity = row["key"], row["period"], row["source_url"]
                previous = snapshots.get(identity)
                if previous is None or previous[0] <= meta["fetched_at"]:
                    snapshots[identity] = meta["fetched_at"], row
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: invalid CNY trade snapshot ({type(exc).__name__})")
    checked = 0
    for row in observations:
        if urlparse(row["source_url"]).hostname != "fdi.mofcom.gov.cn":
            continue
        checked += 1
        candidate = snapshots.get((row["key"], row["period"], row["source_url"]))
        if candidate is None or any(candidate[1][field] != row[field] for field in ("value", "published", "source_title")):
            errors.append(f"{row['key']} {row['period']}: missing or mismatched CNY source snapshot")
    return {"cny_snapshot_count": len(valid),
            "cny_snapshot_checked_observations": checked, "cny_snapshot_errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit local observation integrity and coverage")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--as-of", type=datetime.fromisoformat,
                        help="ISO date/time for reproducible coverage status; default is now")
    args = parser.parse_args()
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM observations ORDER BY key, period")]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    basic = audit_observations(rows)
    snapshots = audit_trade_snapshots(SNAPSHOT_ROOT, rows, BUNDLED_SNAPSHOT_ROOT)
    fiscal_snapshots = audit_fiscal_snapshots(SNAPSHOT_ROOT, rows, BUNDLED_SNAPSHOT_ROOT)
    nbs_gap_snapshots = audit_nbs_gap_snapshots(SNAPSHOT_ROOT, rows, BUNDLED_SNAPSHOT_ROOT)
    finance_snapshots = audit_finance_snapshots(SNAPSHOT_ROOT, rows, BUNDLED_SNAPSHOT_ROOT)
    cny_snapshots = audit_cny_snapshots(SNAPSHOT_ROOT, rows, BUNDLED_SNAPSHOT_ROOT)
    series = {}
    for row in rows:
        series.setdefault(row["key"], []).append(row)
    recent = coverage(series, as_of=args.as_of)
    historical = coverage(series, window=60, as_of=args.as_of)
    report = {
        "created_at": now(), "database_integrity": integrity, **basic, **snapshots,
        **fiscal_snapshots, **nbs_gap_snapshots, **finance_snapshots, **cny_snapshots,
        "errors": (basic["errors"] + snapshots["snapshot_errors"]
                   + fiscal_snapshots["fiscal_snapshot_errors"]
                   + nbs_gap_snapshots["nbs_gap_snapshot_errors"]
                   + finance_snapshots["finance_snapshot_errors"]
                   + cny_snapshots["cny_snapshot_errors"]),
        "coverage_as_of": recent["as_of"],
        "coverage_24m_pct": recent["coverage_pct"],
        "coverage_60m_pct": historical["coverage_pct"],
        "indicator_60m": [
            {"key": item["key"], "observed": item["observed"],
             "expected": item["expected"], "coverage_pct": item["coverage_pct"]}
            for item in historical["metrics"]
        ],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Audit written to {args.output}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if integrity != "ok" or report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
