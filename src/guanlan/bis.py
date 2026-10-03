"""BIS 官方批量数据：政策利率、信贷/GDP 缺口与有效汇率。"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import time
from datetime import datetime, timezone
from zipfile import BadZipFile, ZipFile

import pandas as pd
import pycountry
import requests


BIS_POLICY_URL = "https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip"
BIS_CREDIT_URL = "https://data.bis.org/static/bulk/WS_CREDIT_GAP_csv_flat.zip"
BIS_EER_URL = "https://data.bis.org/static/bulk/WS_EER_csv_flat.zip"
BIS_POLICY_PAGE = "https://data.bis.org/topics/CBPOL"
BIS_CREDIT_PAGE = "https://data.bis.org/topics/CREDIT_GAPS"
BIS_EER_PAGE = "https://data.bis.org/topics/EER"
BIS_LEGAL_PAGE = "https://data.bis.org/help/legal"
POLICY_ARCHIVE_LIMIT = 20 * 1024 * 1024
CREDIT_ARCHIVE_LIMIT = 5 * 1024 * 1024
EER_ARCHIVE_LIMIT = 16 * 1024 * 1024
POLICY_ROWS_LIMIT = 1_000_000
CREDIT_ROWS_LIMIT = 100_000
EER_ROWS_LIMIT = 2_000_000

FREQ = "FREQ:Frequency"
AREA = "REF_AREA:Reference area"
BORROWERS_AREA = "BORROWERS_CTY:Borrowers' country"
PERIOD = "TIME_PERIOD:Time period or range"
VALUE = "OBS_VALUE:Observation Value"
UNIT = "UNIT_MEASURE:Unit of measure"
MULTIPLIER = "UNIT_MULT:Unit Multiplier"
STATUS = "OBS_STATUS:Observation Status"
BORROWERS = "TC_BORROWERS:Borrowing sector"
LENDERS = "TC_LENDERS:Lending sector"
GAP_TYPE = "CG_DTYPE:Credit gap data type"
EER_TYPE = "EER_TYPE:Type"
EER_BASKET = "EER_BASKET:Basket"


def _code(label: str) -> str:
    return str(label).split(":", 1)[0].strip()


def _area(raw: str) -> tuple[str, str | None, str]:
    code = _code(raw)
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError(f"BIS 地区代码无效：{code}")
    name = raw.split(":", 1)[1].strip() if ":" in raw else code
    if code == "XM":
        return code, None, name  # 欧元区为区域汇总，不纳入国家比较。
    country = pycountry.countries.get(alpha_2=code)
    if country is None:
        raise ValueError(f"BIS 地区代码无法映射为 ISO3：{code}")
    return code, country.alpha_3, name


def _number(raw: str, status: str) -> float | None:
    if status == "M":
        if str(raw).strip().lower() not in ("", "nan"):
            raise ValueError("BIS 缺失状态与数值不一致")
        return None
    if status != "A":
        raise ValueError(f"未知 BIS 观测状态：{status}")
    try:
        value = float(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("BIS 正常观测缺少有效数值") from exc
    if not math.isfinite(value):
        raise ValueError("BIS 观测包含非有限数值")
    return value


def _rows(content: bytes, expected_file: str, archive_limit: int, row_limit: int,
          required: set[str]):
    if len(content) > archive_limit:
        raise ValueError("BIS 压缩包超过预设大小上限")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != expected_file or infos[0].is_dir():
                raise ValueError("BIS 压缩包文件结构与预期不符")
            if infos[0].file_size > 600 * 1024 * 1024:
                raise ValueError("BIS 解压文件超过预设大小上限")
            with archive.open(infos[0]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                if reader.fieldnames is None or not required <= set(reader.fieldnames):
                    raise ValueError("BIS CSV 缺少必要字段")
                for index, row in enumerate(reader, start=1):
                    if index > row_limit:
                        raise ValueError("BIS CSV 行数超过预设上限")
                    yield row
    except BadZipFile as exc:
        raise ValueError("BIS 压缩包损坏") from exc


def _metadata(frame: pd.DataFrame, content: bytes, url: str, page: str,
              source_last_modified_http: str | None, excluded_aggregates: int) -> dict:
    return {
        "provider": "Bank for International Settlements (BIS)",
        "source_url": url,
        "methodology_url": page,
        "terms_url": BIS_LEGAL_PAGE,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_last_modified_http": source_last_modified_http,
        "source_archive_sha256": hashlib.sha256(content).hexdigest(),
        "rows": len(frame),
        "countries": int(frame.country_code.nunique()),
        "first_date": frame.date.min().date().isoformat(),
        "last_date": frame.date.max().date().isoformat(),
        "excluded_euro_area_rows": excluded_aggregates,
    }


def normalize_bis_policy_zip(content: bytes, source_last_modified_http: str | None = None
                             ) -> tuple[pd.DataFrame, dict]:
    """流式跳过日度行，只保留官方月末政策利率，不自行月均化。"""
    required = {FREQ, AREA, PERIOD, VALUE, UNIT, MULTIPLIER, STATUS,
                "COMPILATION:Compilation", "SOURCE_REF:Publication Source"}
    rows = []
    notes: dict[str, dict] = {}
    excluded = 0
    for row in _rows(content, "WS_CBPOL_csv_flat.csv", POLICY_ARCHIVE_LIMIT,
                     POLICY_ROWS_LIMIT, required):
        frequency = _code(row[FREQ])
        if frequency not in ("D", "M"):
            raise ValueError(f"BIS 政策利率频率未知：{frequency}")
        if frequency == "D":
            continue
        if _code(row[UNIT]) != "368" or _code(row[MULTIPLIER]) != "0":
            raise ValueError("BIS 月度政策利率单位发生变化")
        area_code, country_code, name = _area(row[AREA])
        if country_code is None:
            excluded += 1
            continue
        period = row[PERIOD].strip()
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise ValueError(f"BIS 月度政策利率日期无效：{period}")
        status = _code(row[STATUS])
        rows.append({"country_code": country_code, "bis_area_code": area_code,
                     "country_name": name, "date": pd.Timestamp(period + "-01"),
                     "value": _number(row[VALUE], status), "obs_status": status})
        note = {"compilation": row["COMPILATION:Compilation"],
                "source_ref": row["SOURCE_REF:Publication Source"]}
        if area_code in notes and notes[area_code] != note:
            raise ValueError(f"BIS {area_code} 月度政策利率序列注释不一致")
        notes[area_code] = note
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["country_code", "date"]).any():
        raise ValueError("BIS 月度政策利率为空或存在重复日期")
    frame = frame.sort_values(["country_code", "date"]).reset_index(drop=True)
    meta = _metadata(frame, content, BIS_POLICY_URL, BIS_POLICY_PAGE,
                     source_last_modified_http, excluded)
    meta.update({"frequency": "monthly", "observation": "last business day of month",
                 "unit": "per cent per year", "country_series_notes": notes,
                 "missing_observations": int(frame.value.isna().sum())})
    return frame, meta


def normalize_bis_credit_zip(content: bytes, source_last_modified_http: str | None = None
                             ) -> tuple[pd.DataFrame, dict]:
    """只取私人非金融部门、所有放贷部门的季度比率、趋势与缺口。"""
    required = {FREQ, BORROWERS_AREA, BORROWERS, LENDERS, GAP_TYPE,
                PERIOD, VALUE, UNIT, MULTIPLIER, STATUS}
    types = {"A": "ratio", "B": "trend", "C": "gap"}
    rows = []
    excluded = 0
    for row in _rows(content, "WS_CREDIT_GAP_csv_flat.csv", CREDIT_ARCHIVE_LIMIT,
                     CREDIT_ROWS_LIMIT, required):
        if (_code(row[FREQ]) != "Q" or _code(row[BORROWERS]) != "P"
                or _code(row[LENDERS]) != "A" or _code(row[UNIT]) != "770"
                or _code(row[MULTIPLIER]) != "0"):
            raise ValueError("BIS 信贷缺口关键口径发生变化")
        kind = _code(row[GAP_TYPE])
        if kind not in types:
            raise ValueError(f"BIS 信贷缺口指标类型未知：{kind}")
        area_code, country_code, name = _area(row[BORROWERS_AREA])
        if country_code is None:
            excluded += 1
            continue
        period = row[PERIOD].strip()
        if not re.fullmatch(r"\d{4}-Q[1-4]", period):
            raise ValueError(f"BIS 信贷缺口季度无效：{period}")
        year, quarter = int(period[:4]), int(period[-1])
        date = pd.Timestamp(year, quarter * 3, 1) + pd.offsets.MonthEnd(0)
        status = _code(row[STATUS])
        rows.append({"country_code": country_code, "bis_area_code": area_code,
                     "country_name": name, "date": date, "period": period,
                     "measure": types[kind], "value": _number(row[VALUE], status),
                     "obs_status": status})
    frame = pd.DataFrame(rows)
    keys = ["country_code", "date", "measure"]
    if frame.empty or frame.duplicated(keys).any():
        raise ValueError("BIS 信贷缺口为空或存在重复主键")
    frame = frame.sort_values(keys).reset_index(drop=True)
    pivot = frame.pivot(index=["country_code", "date"], columns="measure", values="value")
    complete = pivot.dropna(subset=["ratio", "trend", "gap"])
    if complete.empty:
        raise ValueError("BIS 信贷缺口缺少可勾稽的比率、趋势和缺口")
    residual = (complete.ratio - complete.trend - complete.gap).abs()
    if residual.max() > 0.001:
        raise ValueError("BIS 信贷缺口与比率减趋势无法勾稽")
    meta = _metadata(frame, content, BIS_CREDIT_URL, BIS_CREDIT_PAGE,
                     source_last_modified_http, excluded)
    meta.update({"frequency": "quarterly", "measures": {
        "ratio": "private non-financial sector credit / GDP, percent",
        "trend": "one-sided HP filtered credit / GDP trend, percent",
        "gap": "ratio minus trend, percentage points",
    }, "measure_coverage": {
        measure: {"rows": len(group), "countries": int(group.country_code.nunique()),
                  "first_date": group.date.min().date().isoformat(),
                  "last_date": group.date.max().date().isoformat()}
        for measure, group in frame.groupby("measure")
    }, "reconciled_country_quarters": len(complete),
        "max_reconciliation_error_pp": float(residual.max())})
    return frame, meta


def normalize_bis_eer_zip(content: bytes, source_last_modified_http: str | None = None
                          ) -> tuple[pd.DataFrame, dict]:
    """只保留宽口径名义与实际月度 EER；欧元区作为区域汇总显式保留。"""
    required = {FREQ, EER_TYPE, EER_BASKET, AREA, PERIOD, VALUE, UNIT, STATUS}
    declarations: set[tuple[str, str, str]] = set()
    rows = []
    metadata_rows = 0
    for row in _rows(content, "WS_EER_csv_flat.csv", EER_ARCHIVE_LIMIT,
                     EER_ROWS_LIMIT, required):
        kind = _code(row[EER_TYPE])
        basket = _code(row[EER_BASKET])
        area_code = _code(row[AREA])
        period = row[PERIOD].strip()
        if not period:
            metadata_rows += 1
            if _code(row[UNIT]) != "882" or str(row[VALUE]).strip():
                raise ValueError("BIS 有效汇率系列定义的基期或结构发生变化")
            declarations.add((kind, basket, area_code))
            continue
        frequency = _code(row[FREQ])
        if frequency not in ("D", "M") or kind not in ("N", "R") or basket not in ("B", "N"):
            raise ValueError("BIS 有效汇率频率、类型或篮子未知")
        if frequency == "D" or basket == "N":
            continue
        if (kind, basket, area_code) not in declarations:
            raise ValueError("BIS 有效汇率观测缺少系列定义")
        if row[UNIT].strip():
            raise ValueError("BIS 有效汇率观测单位字段发生变化")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise ValueError(f"BIS 月度有效汇率日期无效：{period}")
        bis_code, country_code, name = _area(row[AREA])
        if bis_code == "XM":
            country_code = "XEA"  # 内部区域代码；不是 ISO3 国家代码。
        status = _code(row[STATUS])
        value = _number(row[VALUE], status)
        if value is not None and value <= 0:
            raise ValueError("BIS 有效汇率指数必须为正")
        rows.append({"country_code": country_code, "bis_area_code": bis_code,
                     "country_name": name, "area_type": "aggregate" if bis_code == "XM" else "country",
                     "date": pd.Timestamp(period + "-01"),
                     "measure": "real" if kind == "R" else "nominal",
                     "value": value, "obs_status": status})
    frame = pd.DataFrame(rows)
    keys = ["country_code", "date", "measure"]
    if frame.empty or frame.duplicated(keys).any():
        raise ValueError("BIS 月度有效汇率为空或存在重复主键")
    frame = frame.sort_values(keys).reset_index(drop=True)
    meta = _metadata(frame, content, BIS_EER_URL, BIS_EER_PAGE,
                     source_last_modified_http, 0)
    meta.update({
        "frequency": "monthly", "basket": "broad", "base": "2020 = 100",
        "countries": int(frame.loc[frame.area_type == "country", "country_code"].nunique()),
        "aggregate_areas": int(frame.loc[frame.area_type == "aggregate", "country_code"].nunique()),
        "areas": int(frame.country_code.nunique()),
        "series_definition_rows": metadata_rows,
        "measures": {"nominal": "trade-weighted nominal effective exchange rate index",
                     "real": "CPI-adjusted real effective exchange rate index"},
        "measure_coverage": {measure: {"rows": len(group),
                                      "areas": int(group.country_code.nunique()),
                                      "first_date": group.date.min().date().isoformat(),
                                      "last_date": group.date.max().date().isoformat()}
                             for measure, group in frame.groupby("measure")},
        "missing_observations": int(frame.value.isna().sum()),
    })
    return frame, meta


def download_bis_zip(url: str) -> tuple[bytes, str | None]:
    session = requests.Session()
    session.headers.update({"User-Agent": "GuanlanMacro/0.3 (educational research)"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=(10, 90))
            response.raise_for_status()
            return response.content, response.headers.get("Last-Modified")
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"BIS 数据下载失败：{url}") from last_error
