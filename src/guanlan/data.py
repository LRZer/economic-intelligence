"""官方宏观与贸易数据的读取、标准化和快照管理。"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pandas as pd
import requests

from .catalog import INDICATORS

WORLD_BANK_BASE = "https://api.worldbank.org/v2"
COMTRADE_BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
CATALOG_NAME = "release_catalog.sqlite"

# 联合国公开预览接口适合构建真实样例，不代表全球贸易数据全量。
TRADE_REPORTERS = {"CHN": 156, "USA": 842, "DEU": 276, "JPN": 392, "IND": 699}
TRADE_YEARS = (2023, 2024)


def _get_json(session: requests.Session, url: str, params: dict) -> object:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=(10, 50))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"数据接口请求失败：{url}") from last_error


def _world_bank_pages(session: requests.Session, url: str, params: dict) -> tuple[list[dict], dict]:
    first = _get_json(session, url, {**params, "page": 1})
    if not isinstance(first, list) or len(first) != 2 or not isinstance(first[0], dict):
        raise ValueError(f"世界银行接口返回结构异常：{url}")
    meta, rows = first
    all_rows = list(rows or [])
    for page in range(2, int(meta.get("pages", 1)) + 1):
        result = _get_json(session, url, {**params, "page": page})
        if not isinstance(result, list) or len(result) != 2:
            raise ValueError(f"世界银行接口第 {page} 页结构异常")
        all_rows.extend(result[1] or [])
    return all_rows, meta


def normalize_wdi_records(records: list[dict], countries: dict[str, dict]) -> pd.DataFrame:
    normalized = []
    for item in records:
        code = item.get("countryiso3code")
        if code not in countries:
            continue
        indicator = item.get("indicator") or {}
        year = item.get("date")
        if not year or not str(year).isdigit():
            continue
        country = countries[code]
        normalized.append(
            {
                "country_code": code,
                "country_name": country["name"],
                "region": country["region"],
                "income_level": country["income_level"],
                "year": int(year),
                "indicator_code": indicator.get("id"),
                "value": item.get("value"),
            }
        )
    frame = pd.DataFrame.from_records(
        normalized,
        columns=["country_code", "country_name", "region", "income_level", "year", "indicator_code", "value"],
    )
    if frame.empty:
        raise ValueError("没有获得可用的国家年度观测值")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    keys = ["country_code", "year", "indicator_code"]
    if frame.duplicated(keys).any():
        raise ValueError("世界银行数据存在重复的国家、年份、指标组合")
    return frame.sort_values(keys).reset_index(drop=True)


def fetch_wdi(start: int = 2000, end: int = 2025) -> tuple[pd.DataFrame, dict]:
    if start > end:
        raise ValueError("开始年份不能晚于结束年份")
    session = requests.Session()
    session.headers.update({"User-Agent": "GuanlanMacro/0.1 (educational research)"})
    country_rows, _ = _world_bank_pages(
        session, f"{WORLD_BANK_BASE}/country", {"format": "json", "per_page": 400}
    )
    countries = {
        row["id"]: {
            "name": row["name"],
            "region": row["region"]["value"],
            "income_level": row["incomeLevel"]["value"],
        }
        for row in country_rows
        if row.get("region", {}).get("id") != "NA" and row.get("id")
    }
    records: list[dict] = []
    source_updated = None
    codes = [indicator.code for indicator in INDICATORS]
    for index in range(0, len(codes), 2):
        batch = ";".join(codes[index : index + 2])
        rows, meta = _world_bank_pages(
            session,
            f"{WORLD_BANK_BASE}/country/all/indicator/{batch}",
            {"source": 2, "date": f"{start}:{end}", "format": "json", "per_page": 20000},
        )
        records.extend(rows)
        source_updated = meta.get("lastupdated", source_updated)
    frame = normalize_wdi_records(records, countries)
    return frame, {
        "provider": "World Bank WDI",
        "source_url": "https://api.worldbank.org/v2/",
        "source_last_updated": source_updated,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_year": start,
        "end_year": end,
        "countries": int(frame.country_code.nunique()),
        "indicators": int(frame.indicator_code.nunique()),
        "rows": len(frame),
        "observed_values": int(frame.value.notna().sum()),
    }


def normalize_comtrade_records(records: list[dict]) -> pd.DataFrame:
    normalized = []
    for item in records:
        if item.get("cmdCode") != "TOTAL" or item.get("partnerCode") == 0:
            continue
        if item.get("partner2Code") != 0 or item.get("customsCode") != "C00" or item.get("motCode") != 0:
            continue
        partner = item.get("partnerISO")
        if not partner or len(partner) != 3 or not partner.isalpha():
            continue
        value = item.get("primaryValue")
        if value is None or float(value) < 0:
            continue
        normalized.append(
            {
                "reporter_code": item["reporterISO"],
                "reporter_name": item.get("reporterDesc") or item["reporterISO"],
                "partner_code": partner,
                "partner_name": item.get("partnerDesc") or partner,
                "year": int(item["refYear"]),
                "flow": item["flowCode"],
                "trade_usd": float(value),
            }
        )
    frame = pd.DataFrame.from_records(
        normalized,
        columns=["reporter_code", "reporter_name", "partner_code", "partner_name", "year", "flow", "trade_usd"],
    )
    if frame.empty:
        return frame
    keys = ["reporter_code", "partner_code", "year", "flow"]
    if frame.duplicated(keys).any():
        raise ValueError("贸易数据存在重复的报告国、伙伴国、年份、流向组合")
    return frame.sort_values(keys).reset_index(drop=True)


def fetch_trade_preview() -> tuple[pd.DataFrame, dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": "GuanlanMacro/0.1 (educational research)"})
    records = []
    successful_queries = []
    for reporter_code, m49 in TRADE_REPORTERS.items():
        for year in TRADE_YEARS:
            for flow in ("X", "M"):
                result = _get_json(
                    session,
                    COMTRADE_BASE,
                    {
                        "period": year,
                        "reporterCode": m49,
                        "cmdCode": "TOTAL",
                        "flowCode": flow,
                        "maxRecords": 500,
                        "includeDesc": "true",
                    },
                )
                if not isinstance(result, dict) or "data" not in result:
                    raise ValueError("联合国 Comtrade 接口返回结构异常")
                if int(result.get("count", 0)) >= 500:
                    raise ValueError(f"{reporter_code} {year} {flow} 超出公开预览上限，可能被截断")
                records.extend(result["data"])
                successful_queries.append(f"{reporter_code}/{year}/{flow}")
    frame = normalize_comtrade_records(records)
    if frame.empty:
        raise ValueError("联合国 Comtrade 未返回可用贸易记录")
    return frame, {
        "provider": "UN Comtrade public preview",
        "source_url": COMTRADE_BASE,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "5 个报告经济体；2023—2024；全部商品；出口与进口；伙伴国汇总",
        "queries": successful_queries,
        "rows": len(frame),
        "reporters": int(frame.reporter_code.nunique()),
    }


def save_snapshot(frame: pd.DataFrame, metadata: dict, stem: str, directory: Path = DEFAULT_DATA_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}.parquet"
    temp = directory / f"{stem}.parquet.tmp"
    frame.to_parquet(temp, index=False)
    checksum = hashlib.sha256(temp.read_bytes()).hexdigest()
    stored_metadata = {**metadata, "parquet_sha256": checksum}
    os.replace(temp, target)
    meta_target = directory / f"{stem}.json"
    meta_temp = directory / f"{stem}.json.tmp"
    meta_temp.write_text(json.dumps(stored_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(meta_temp, meta_target)


def snapshot_catalog(directory: Path = DEFAULT_DATA_DIR) -> dict[str, str]:
    """一次读取全部活动快照引用，供页面在一次执行中使用同一批次视图。"""
    catalog_path = directory / CATALOG_NAME
    if not catalog_path.exists():
        return {}
    with sqlite3.connect(catalog_path, timeout=30) as connection:
        rows = connection.execute("SELECT stem, relative_base FROM active_snapshots").fetchall()
    return dict(rows)


def snapshot_paths(stem: str, directory: Path = DEFAULT_DATA_DIR,
                   snapshot_map: Mapping[str, str] | None = None) -> tuple[Path, Path]:
    if not stem or not all(char.isalnum() or char == "_" for char in stem):
        raise ValueError("快照名称只能包含字母、数字和下划线")
    active = snapshot_catalog(directory) if snapshot_map is None else snapshot_map
    base = Path(active.get(stem, stem))
    if base.is_absolute() or ".." in base.parts or base.suffix:
        raise ValueError(f"{stem} 活动快照路径无效")
    return directory / f"{base}.parquet", directory / f"{base}.json"


def load_snapshot(stem: str, directory: Path = DEFAULT_DATA_DIR,
                  snapshot_map: Mapping[str, str] | None = None) -> tuple[pd.DataFrame, dict]:
    target, meta_target = snapshot_paths(stem, directory, snapshot_map)
    if not target.exists() or not meta_target.exists():
        raise FileNotFoundError(f"缺少 {stem} 数据快照；请先运行 python scripts/refresh_data.py")
    metadata = json.loads(meta_target.read_text(encoding="utf-8"))
    expected = metadata.get("parquet_sha256")
    if expected is not None and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise ValueError(f"{stem} 数据与元数据校验失败；请重新刷新该快照")
    return pd.read_parquet(target), metadata


def _init_catalog(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS active_snapshots (
            stem TEXT PRIMARY KEY, relative_base TEXT NOT NULL, batch_id TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS refresh_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at_utc TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            status TEXT NOT NULL,
            stems_json TEXT NOT NULL,
            previous_json TEXT,
            error TEXT
        )
    """)
    connection.commit()


def _record_failed_refresh(directory: Path, batch_id: str, operation: str,
                           stems: list[str], error: str) -> None:
    with sqlite3.connect(directory / CATALOG_NAME, timeout=30) as connection:
        _init_catalog(connection)
        connection.execute(
            "INSERT INTO refresh_events (at_utc, batch_id, operation, status, stems_json, error) "
            "VALUES (?, ?, ?, 'failed', ?, ?)",
            (datetime.now(timezone.utc).isoformat(), batch_id, operation,
             json.dumps(stems, ensure_ascii=False), error[:2000]),
        )


def record_refresh_failure(operation: str, stems: list[str], error: Exception | str,
                           directory: Path = DEFAULT_DATA_DIR) -> str:
    """记录来源抓取或建模阶段失败，此时尚未进入快照发布。"""
    directory.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    _record_failed_refresh(directory, batch_id, operation, stems, str(error))
    return batch_id


def publish_snapshots(snapshots: Mapping[str, tuple[pd.DataFrame, dict]],
                      directory: Path = DEFAULT_DATA_DIR, operation: str = "refresh") -> str:
    """先构建不可变文件，再以一次 SQLite 事务切换整批活动快照。"""
    if not snapshots:
        raise ValueError("至少需要一份快照")
    stems = sorted(snapshots)
    directory.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    staging = None
    release = directory / "releases" / batch_id
    try:
        for stem in stems:
            snapshot_paths(stem, directory, {})
            frame, metadata = snapshots[stem]
            if frame.empty:
                raise ValueError(f"{stem} 快照为空")
            if "rows" in metadata and int(metadata["rows"]) != len(frame):
                raise ValueError(f"{stem} 快照行数与元数据不符")
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=directory))
        for stem in stems:
            frame, metadata = snapshots[stem]
            save_snapshot(frame, metadata, stem, staging)
            load_snapshot(stem, staging, {})
        release.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, release)
        with sqlite3.connect(directory / CATALOG_NAME, timeout=30) as connection:
            _init_catalog(connection)
            connection.execute("BEGIN IMMEDIATE")
            previous = {stem: reference for stem, reference in connection.execute(
                "SELECT stem, relative_base FROM active_snapshots"
            ).fetchall() if stem in stems}
            for stem in stems:
                connection.execute(
                    "INSERT INTO active_snapshots (stem, relative_base, batch_id) VALUES (?, ?, ?) "
                    "ON CONFLICT(stem) DO UPDATE SET relative_base=excluded.relative_base, batch_id=excluded.batch_id",
                    (stem, f"releases/{batch_id}/{stem}", batch_id),
                )
            connection.execute(
                "INSERT INTO refresh_events (at_utc, batch_id, operation, status, stems_json, previous_json) "
                "VALUES (?, ?, ?, 'published', ?, ?)",
                (datetime.now(timezone.utc).isoformat(), batch_id, operation,
                 json.dumps(stems, ensure_ascii=False), json.dumps(previous, ensure_ascii=False)),
            )
            connection.commit()
        return batch_id
    except Exception as exc:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        release_active = False
        if release.exists():
            try:
                active = snapshot_catalog(directory)
            except (OSError, sqlite3.Error):
                active = None
            if active is not None:
                release_active = any(active.get(stem) == f"releases/{batch_id}/{stem}" for stem in stems)
            if active is not None and not release_active:
                shutil.rmtree(release)
        if release_active:
            exc.add_note("活动目录已指向此批次；数据目录保留，请核查批次状态")
            raise
        try:
            _record_failed_refresh(directory, batch_id, operation, stems, str(exc))
            setattr(exc, "_guanlan_refresh_logged", True)
        except (OSError, sqlite3.Error) as audit_error:
            exc.add_note(f"刷新失败记录无法写入：{audit_error}")
        raise


def refresh_audit(directory: Path = DEFAULT_DATA_DIR, limit: int = 20) -> pd.DataFrame:
    """返回最近的发布及失败事件；仓库随附的初始快照没有本地刷新事件。"""
    if limit < 1:
        raise ValueError("审计事件条数必须为正")
    catalog_path = directory / CATALOG_NAME
    columns = ["at_utc", "batch_id", "operation", "status", "stems", "previous", "error"]
    if not catalog_path.exists():
        return pd.DataFrame(columns=columns)
    with sqlite3.connect(catalog_path, timeout=30) as connection:
        rows = connection.execute(
            "SELECT at_utc, batch_id, operation, status, stems_json, previous_json, error "
            "FROM refresh_events ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return pd.DataFrame(
        [(at, batch, operation, status, json.loads(stems),
          json.loads(previous) if previous else None, error)
         for at, batch, operation, status, stems, previous, error in rows],
        columns=columns,
    )


def restore_batch(target_batch_id: str, directory: Path = DEFAULT_DATA_DIR) -> str:
    """仅回退当前仍完整生效的目标批次，保持整批切换和审计记录。"""
    catalog_path = directory / CATALOG_NAME
    if not catalog_path.exists():
        raise ValueError("没有可回退的本地刷新批次")
    with sqlite3.connect(catalog_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        event = connection.execute(
            "SELECT stems_json, previous_json FROM refresh_events "
            "WHERE batch_id = ? AND status = 'published'", (target_batch_id,),
        ).fetchone()
        if event is None:
            raise ValueError("目标批次不存在或并非已发布批次")
        stems = json.loads(event[0])
        previous = json.loads(event[1])
        current_rows = [row for row in connection.execute(
            "SELECT stem, relative_base, batch_id FROM active_snapshots"
        ).fetchall() if row[0] in stems]
        current = {stem: (relative_base, batch_id) for stem, relative_base, batch_id in current_rows}
        if set(current) != set(stems) or any(current[stem][1] != target_batch_id for stem in stems):
            raise ValueError("目标批次已被后续刷新部分覆盖，请先回退更新的批次")
        for stem in stems:
            reference = previous.get(stem, stem)
            load_snapshot(stem, directory, {stem: reference})
        restore_id = uuid.uuid4().hex
        for stem in stems:
            if stem in previous:
                connection.execute(
                    "UPDATE active_snapshots SET relative_base = ?, batch_id = ? WHERE stem = ?",
                    (previous[stem], previous[stem].split("/")[1], stem),
                )
            else:
                connection.execute("DELETE FROM active_snapshots WHERE stem = ?", (stem,))
        connection.execute(
            "INSERT INTO refresh_events (at_utc, batch_id, operation, status, stems_json, previous_json) "
            "VALUES (?, ?, ?, 'restored', ?, ?)",
            (datetime.now(timezone.utc).isoformat(), restore_id, f"rollback:{target_batch_id}",
             json.dumps(stems, ensure_ascii=False),
             json.dumps({stem: current[stem][0] for stem in stems}, ensure_ascii=False)),
        )
        connection.commit()
    return restore_id
