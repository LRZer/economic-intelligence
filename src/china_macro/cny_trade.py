"""National CNY trade tables republished by MOFCOM, with explicit monthly rates."""
from __future__ import annotations

from .paths import DATA_ROOT

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .collector import compact, record
from .finance import table_grid

BASE = "https://fdi.mofcom.gov.cn"
LIST_URL = BASE + "/cipa-api/statistics/web/list"
DETAIL_URL = BASE + "/cipa-api/statistics/web/get"
PAGE_URL = BASE + "/come-datatongji-con.html?id="
SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"


def request_source(session: requests.Session, url: str, body: dict | None = None) -> bytes:
    if url not in {LIST_URL, DETAIL_URL} and not re.fullmatch(re.escape(DETAIL_URL) + r"\?id=\d+", url):
        raise ValueError("Not a selected MOFCOM statistical resource")
    headers = {"User-Agent": "ChinaMacroObservatory/1.0", "Origin": BASE,
               "Referer": BASE + "/come-datatongji-list.html"}
    try:
        response = (session.post(url, json=body, headers=headers, timeout=(5, 18))
                    if body is not None else session.get(url, headers=headers, timeout=(5, 18)))
        response.raise_for_status()
        raw = response.content
    except requests.exceptions.SSLError:
        # Windows' native verified TLS transport supports this source's server
        # configuration. Keep certificate verification on; never use curl -k.
        executable = shutil.which("curl.exe") if os.name == "nt" else None
        if executable is None:
            raise
        args = [executable, "--silent", "--show-error", "--fail", "--max-time", "23", url]
        for key, value in headers.items():
            args += ["--header", f"{key}: {value}"]
        with tempfile.TemporaryDirectory() as directory:
            if body is not None:
                path = Path(directory) / "request.json"
                path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
                args += ["--header", "Content-Type: application/json;charset=UTF-8", "--data-binary", "@" + str(path)]
            result = subprocess.run(args, capture_output=True, timeout=26, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            raw = result.stdout
    if len(raw) > 1_000_000:
        raise ValueError("MOFCOM resource unexpectedly large")
    return raw


def discover_sources(session: requests.Session, pages: int = 1) -> list[dict]:
    found = {}
    for page in range(1, pages + 1):
        payload = json.loads(request_source(session, LIST_URL, {"menuId": 1, "page": page,
                             "keyWord": "全国进出口总值表"}))
        if payload.get("code") != 0 or not isinstance(payload.get("data"), list):
            raise ValueError("MOFCOM statistical directory unavailable")
        for item in payload["data"]:
            # Exclude USD, regional tables, and 1-2 month cumulative reports.
            if re.fullmatch(r"20\d{2}年\d{1,2}月全国进出口总值表（人民币值）", item.get("name", "")):
                found[item["id"]] = item
        if page * 10 >= payload["total"]:
            break
        time.sleep(0.4)
    return list(found.values())


def parse_cny_payload(payload: dict, source_url: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("MOFCOM table response is not a detail object")
    parsed_url = urlparse(source_url)
    if (parsed_url.scheme != "https" or parsed_url.hostname != "fdi.mofcom.gov.cn"
            or parsed_url.path != "/come-datatongji-con.html"):
        raise ValueError("Not an official MOFCOM CNY trade page")
    data = payload.get("data", {})
    ids = parse_qs(parsed_url.query).get("id", [])
    if payload.get("code") != 0 or ids != [str(data.get("id"))] or data.get("source") != "海关总署":
        raise ValueError("MOFCOM table identity or publisher mismatch")
    match = re.fullmatch(r"(20\d{2})年(\d{1,2})月全国进出口总值表（人民币值）", data.get("name", ""))
    if match is None or not 1 <= int(match[2]) <= 12:
        raise ValueError("Not an individual national monthly CNY table")
    year, month = int(match[1]), int(match[2])
    period = f"{year}-{month:02d}"
    published = data.get("issueDate", "")
    datetime.strptime(published, "%Y-%m-%d")
    soup = BeautifulSoup(data.get("content", ""), "html.parser")
    text = compact(soup.get_text())
    if "亿元人民币" not in text:
        raise ValueError("CNY unit not confirmed")
    values, totals = {}, {}
    for table in soup.find_all("table"):
        rate_column = amount_column = None
        for cells in table_grid(table):
            monthly_columns = [i for i, cell in enumerate(cells)
                               if cell == f"{month}月与去年同期同比增减±%"]
            amount_columns = [i for i, cell in enumerate(cells) if cell == f"{month}月"]
            if len(monthly_columns) == 1 and len(amount_columns) == 1:
                rate_column, amount_column = monthly_columns[0], amount_columns[0]
            if not cells or cells[0] not in {"进出口总值", "出口总值", "进口总值", "进出口差额"}:
                continue
            if amount_column is None or rate_column is None:
                raise ValueError("Monthly amount and YoY headers unavailable")
            amount = cells[amount_column].replace(",", "")
            if not re.fullmatch(r"-?\d+(?:\.\d+)?", amount):
                raise ValueError("Invalid national trade amount")
            totals[cells[0]] = float(amount)
            if cells[0] in {"出口总值", "进口总值"}:
                rate = cells[rate_column].rstrip("%")
                if not re.fullmatch(r"-?\d+(?:\.\d+)?", rate):
                    raise ValueError("Invalid explicitly reported monthly growth rate")
                key = "export_yoy" if cells[0] == "出口总值" else "import_yoy"
                row = record(key, float(rate), period, source_url,
                             data["name"] + "（商务部转载海关数据；日期为转载日期）", published)
                if row is None or (key in values and values[key] != row):
                    raise ValueError("Invalid or conflicting national trade rate")
                values[key] = row
    if len(values) != 2 or len(totals) != 4 or any(not math.isfinite(v) for v in totals.values()):
        raise ValueError("Incomplete national trade table")
    if (abs(totals["进出口总值"] - totals["出口总值"] - totals["进口总值"]) > .21
            or abs(totals["进出口差额"] - totals["出口总值"] + totals["进口总值"]) > .21):
        raise ValueError("Trade amounts do not reconcile within table rounding")
    return list(values.values())


def save_snapshot(raw: bytes, source_url: str, rows: list[dict], root: Path = SNAPSHOT_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    stem = f"mofcom-cny-{digest}"
    (root / f"{stem}.json").write_bytes(raw)
    (root / f"{stem}.meta.json").write_text(json.dumps({
        "file": stem + ".json", "sha256": digest, "source_url": source_url,
        "record_count": len(rows), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_cny_trade(known: set[tuple[str, str]] | None = None,
                      pages: int = 1) -> tuple[list[dict], list[str]]:
    session = requests.Session()
    rows, errors = [], []
    try:
        for item in discover_sources(session, pages):
            period = re.sub(r"年(\d+)月.*", lambda m: f"-{int(m[1]):02d}", item["name"])
            if known and all((key, period) in known for key in ("export_yoy", "import_yoy")):
                continue
            url = PAGE_URL + str(item["id"])
            raw = request_source(session, DETAIL_URL + "?id=" + str(item["id"]))
            parsed = parse_cny_payload(json.loads(raw), url)
            save_snapshot(raw, url, parsed)
            rows.extend(row for row in parsed if known is None or (row["key"], row["period"]) not in known)
            time.sleep(0.4)
    except (requests.RequestException, subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"商务部人民币外贸表：读取或核验失败（{type(exc).__name__}）")
    return rows, errors


if __name__ == "__main__":
    from .app import connect, initialize, now, record_run, save_rows
    initialize()
    started = now()
    with connect() as db:
        known = {(r[0], r[1]) for r in db.execute("SELECT key,period FROM observations")}
    rows, errors = collect_cny_trade(known, pages=10)
    if errors:
        raise SystemExit("; ".join(errors))
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, rows, started)
        after = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        record_run(db, started, "cny_trade_backfill", "complete", len(rows), after - before, [])
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_refresh', ?)", (started,))
    print(f"Parsed {len(rows)} official CNY trade rates; added {after-before}")
