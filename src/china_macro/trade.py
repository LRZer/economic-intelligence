"""Curated USD goods-trade series from MOFCOM's GACC-sourced monthly table."""

from __future__ import annotations

from .paths import DATA_ROOT

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


PAGE_URL = "https://data.mofcom.gov.cn/hwmy/imexmonth.shtml"
API_URL = "https://data.mofcom.gov.cn/datamofcom/front/totalmonth/query"
TITLE = "商务部货物进出口月度统计（数据来源：海关总署；美元）"
SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"
FIELDS = {
    "export_usd": "export_value",
    "import_usd": "import_value",
    "export_usd_yoy": "export_per",
    "import_usd_yoy": "import_per",
}


def _number(item: dict, field: str, low: float, high: float) -> float:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid trade field: {field}")
    if not low <= value <= high:
        raise ValueError(f"Trade field outside guardrail: {field}")
    return float(value)


def parse_trade_payload(payload: object, start: str, end: str) -> list[dict]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list) or not payload[0]:
        raise ValueError("MOFCOM returned no monthly trade data")
    records = payload[0]
    seen: set[str] = set()
    rows: list[dict] = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Invalid MOFCOM trade row")
        raw = item.get("trade_date")
        if not isinstance(raw, str) or not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", raw):
            raise ValueError("Invalid MOFCOM trade month")
        if not start <= raw <= end or raw in seen:
            raise ValueError("MOFCOM trade month is duplicate or outside requested range")
        seen.add(raw)
        values = {key: _number(item, field, -80 if key.endswith("_yoy") else 0,
                               200 if key.endswith("_yoy") else 10000)
                  for key, field in FIELDS.items()}
        total = _number(item, "total_value", 0, 20000)
        balance = _number(item, "imexgap_value", -10000, 10000)
        if abs(total - values["export_usd"] - values["import_usd"]) > 0.06:
            raise ValueError(f"MOFCOM trade sum does not reconcile for {raw}")
        if abs(balance - values["export_usd"] + values["import_usd"]) > 0.06:
            raise ValueError(f"MOFCOM trade balance does not reconcile for {raw}")
        period = f"{raw[:4]}-{raw[4:]}"
        rows.extend({"key": key, "period": period, "value": value,
                     "source_url": PAGE_URL, "source_title": TITLE, "published": ""}
                    for key, value in values.items())
    return sorted(rows, key=lambda row: (row["key"], row["period"]))


def save_source_snapshot(content: bytes, rows: list[dict], start: str, end: str,
                         root: Path = SNAPSHOT_ROOT) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"mofcom-trade-{digest}.json"
    if not path.exists():
        temporary = root / f".{path.name}.{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_page": PAGE_URL, "request_url": API_URL,
        "requested_range": [start, end], "sha256": digest,
        "path": str(path), "observation_count": len(rows),
        "first_period": min(row["period"] for row in rows),
        "last_period": max(row["period"] for row in rows),
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def collect_trade(start: str = "202101", end: str | None = None) -> tuple[list[dict], dict]:
    end = end or datetime.now(timezone.utc).strftime("%Y%m")
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", start) or not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", end) or start > end:
        raise ValueError("Invalid MOFCOM requested date range")
    response = requests.post(API_URL, data={"startDate": start, "endDate": end},
                             headers={"User-Agent": "ChinaMacroObservatory/1.0"}, timeout=(5, 18))
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("MOFCOM response is unexpectedly large")
    rows = parse_trade_payload(response.json(), start, end)
    manifest = save_source_snapshot(response.content, rows, start, end)
    return rows, manifest
